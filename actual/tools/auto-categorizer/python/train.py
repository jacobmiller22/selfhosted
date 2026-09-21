import math
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score

from fetch_data import load_dataset
from text_cleaner import clean_payee_text
from config import MODELS_DIR, DATA_DIR

def remap_historical_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Remap historical consolidated categories (e.g. Gas [J] -> Gas) to active category IDs."""
    db_path = DATA_DIR / "latest_db.sqlite"
    if not db_path.exists():
        return df

    conn = sqlite3.connect(db_path)
    cats = dict(conn.execute("SELECT id, name FROM categories").fetchall())
    active_cats = {r[1]: r[0] for r in conn.execute("SELECT id, name FROM categories WHERE hidden = 0 AND tombstone = 0").fetchall()}

    remap = {
        "Gas [J]": active_cats.get("Gas"),
        "Gas [P]": active_cats.get("Gas"),
        "Common Subscriptions": active_cats.get("Subscriptions"),
        "Subscriptions [J]": active_cats.get("Subscriptions"),
        "Bills [J]": active_cats.get("Bills"),
        "Bills [P]": active_cats.get("Bills"),
        "Savings [J]": active_cats.get("Savings"),
        "Savings [P]": active_cats.get("Savings"),
        "Taxes [J]": active_cats.get("Taxes"),
        "Taxes [P]": active_cats.get("Taxes"),
        "Car Maintenance [J]": active_cats.get("Car Maintenance"),
        "Car Maintenance [P]": active_cats.get("Car Maintenance"),
    }

    df = df.copy()
    cat_names = df["category_id"].map(cats)
    for old_name, new_id in remap.items():
        if new_id:
            mask = cat_names == old_name
            df.loc[mask, "category_id"] = new_id

    return df

def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Extract temporal, numeric, persona, and cleaned text feature attributes."""
    df = df.copy()

    # Clean raw payee strings
    df["raw_payee"] = df["imported_payee"].fillna("").astype(str)
    df["cleaned_payee"] = df["raw_payee"].apply(clean_payee_text)

    # Account persona
    if "persona" not in df.columns:
        df["persona"] = "Joint"

    # Numerical features
    df["amount_log"] = df["amount"].apply(lambda x: math.log1p(abs(x)))
    df["amount_sign"] = df["amount"].apply(lambda x: 1 if x > 0 else -1)

    # Parse date attributes
    dt_series = pd.to_datetime(df["date"], errors="coerce")
    df["day_of_week"] = dt_series.dt.dayofweek.fillna(0).astype(int)
    df["day_of_month"] = dt_series.dt.day.fillna(1).astype(int)
    df["month"] = dt_series.dt.month.fillna(1).astype(int)

    return df

def compute_time_weights(df: pd.DataFrame, half_life_days: float = 180.0, min_weight: float = 0.05) -> np.ndarray:
    """Compute exponential decay sample weights based on transaction date relative to latest date in dataset."""
    dates = pd.to_datetime(df["date"], errors="coerce")
    max_date = dates.max()
    if pd.isna(max_date):
        return np.ones(len(df), dtype=float)

    days_old = (max_date - dates).dt.total_seconds() / 86400.0
    days_old = days_old.fillna(0.0).clip(lower=0.0)

    decay_rate = np.log(2.0) / half_life_days
    weights = np.exp(-decay_rate * days_old)
    return np.maximum(weights, min_weight)

def train_payee_resolver(df: pd.DataFrame, half_life_days: float = 180.0):
    """Train Payee Resolver Pipeline mapping cleaned payee text + account + persona + amount to canonical payee_id."""
    print(f"\n--- Training Model 2: Payee Resolver (Time Decay Half-Life: {half_life_days} days) ---")
    df_valid = df[(df["is_transfer"] == False) & df["payee_id"].notna() & (df["payee_id"] != "")].copy()

    X = df_valid[["cleaned_payee", "account_id", "persona", "amount_log", "amount_sign"]]
    y = df_valid["payee_id"]
    weights = compute_time_weights(df_valid, half_life_days=half_life_days)

    counts = y.value_counts()
    valid_classes = counts[counts >= 2].index
    mask = y.isin(valid_classes)

    X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
        X[mask], y[mask], weights[mask], test_size=0.2, random_state=42, stratify=y[mask]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("text", TfidfVectorizer(analyzer="word", ngram_range=(1, 3), min_df=1, sublinear_tf=True, token_pattern=r"\b\w+\b"), "cleaned_payee"),
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["account_id", "persona"]),
            ("num", StandardScaler(), ["amount_log", "amount_sign"])
        ]
    )

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", LogisticRegression(max_iter=1000, C=5.0))
        ]
    )

    pipeline.fit(X_train, y_train, classifier__sample_weight=w_train)
    y_pred = pipeline.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    print(f"✓ Payee Resolver Accuracy (validation set): {acc * 100:.2f}%")

    # Fit final model on full dataset
    pipeline.fit(X, y, classifier__sample_weight=weights)

    return pipeline, preprocessor

def train_category_classifier(df: pd.DataFrame, half_life_days: float = 180.0):
    """Train Category Classifier Pipeline predicting category_id from cleaned payee, account, persona, date & amount."""
    print(f"\n--- Training Model 3: Category Classifier (Time Decay Half-Life: {half_life_days} days) ---")

    # Remap consolidated historical categories
    df_remapped = remap_historical_categories(df)

    df_valid = df_remapped[(df_remapped["is_transfer"] == False) & df_remapped["category_id"].notna() & (df_remapped["category_id"] != "")].copy()

    # Filter categories with at least 2 samples for stratified evaluation
    counts = df_valid["category_id"].value_counts()
    valid_classes = counts[counts >= 2].index
    df_valid = df_valid[df_valid["category_id"].isin(valid_classes)].copy()

    X = df_valid[["cleaned_payee", "account_id", "persona", "amount_log", "amount_sign", "day_of_week", "day_of_month", "month"]]
    y = df_valid["category_id"]
    weights = compute_time_weights(df_valid, half_life_days=half_life_days)

    X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
        X, y, weights, test_size=0.2, random_state=42, stratify=y
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("text", TfidfVectorizer(analyzer="word", ngram_range=(1, 3), min_df=1, sublinear_tf=True, token_pattern=r"\b\w+\b"), "cleaned_payee"),
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["account_id", "persona"]),
            ("num", StandardScaler(), ["amount_log", "amount_sign", "day_of_week", "day_of_month", "month"])
        ]
    )

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", LogisticRegression(max_iter=1000, C=2.0))
        ]
    )

    pipeline.fit(X_train, y_train, classifier__sample_weight=w_train)
    y_pred = pipeline.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    print(f"✓ Category Classifier Accuracy (validation set): {acc * 100:.2f}%")

    # Fit final model on full dataset
    pipeline.fit(X, y, classifier__sample_weight=weights)

    return pipeline, preprocessor

def train_all_models():
    df = load_dataset()
    df = preprocess_dataframe(df)

    payee_pipeline, _ = train_payee_resolver(df)
    category_pipeline, _ = train_category_classifier(df)

    return df, payee_pipeline, category_pipeline

if __name__ == "__main__":
    train_all_models()
