import math
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score

from fetch_data import load_dataset
from text_cleaner import clean_payee_text
from config import MODELS_DIR

def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Extract temporal, numeric, and cleaned text feature attributes."""
    df = df.copy()
    
    # Clean raw payee strings
    df["raw_payee"] = df["imported_payee"].fillna("").astype(str)
    df["cleaned_payee"] = df["raw_payee"].apply(clean_payee_text)

    # Numerical features
    df["amount_log"] = df["amount"].apply(lambda x: math.log1p(abs(x)))
    df["amount_sign"] = df["amount"].apply(lambda x: 1 if x > 0 else -1)
    
    # Parse date attributes
    dt_series = pd.to_datetime(df["date"], errors="coerce")
    df["day_of_week"] = dt_series.dt.dayofweek.fillna(0).astype(int)
    df["day_of_month"] = dt_series.dt.day.fillna(1).astype(int)
    df["month"] = dt_series.dt.month.fillna(1).astype(int)
    
    return df

def train_payee_resolver(df: pd.DataFrame):
    """Train Payee Resolver Pipeline mapping cleaned payee text + account + amount to canonical payee_id."""
    print("\n--- Training Model 2: Payee Resolver ---")
    df_valid = df[(df["is_transfer"] == False) & df["payee_id"].notna() & (df["payee_id"] != "")].copy()
    
    X = df_valid[["cleaned_payee", "account_id", "amount_log", "amount_sign"]]
    y = df_valid["payee_id"]
    
    counts = y.value_counts()
    stratify = y if counts.min() >= 2 else None
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=stratify
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("text", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True, token_pattern=r"\b\w+\b"), "cleaned_payee"),
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["account_id"]),
            ("num", StandardScaler(), ["amount_log", "amount_sign"])
        ]
    )

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", LogisticRegression(max_iter=1000, C=10.0, class_weight="balanced"))
        ]
    )

    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    
    acc = accuracy_score(y_test, y_pred)
    print(f"✓ Payee Resolver Accuracy (validation set): {acc * 100:.2f}%")
    
    # Fit final model on full dataset for maximum vocabulary and class coverage
    pipeline.fit(X, y)
    
    return pipeline, preprocessor

def train_category_classifier(df: pd.DataFrame):
    """Train Category Classifier Pipeline predicting category_id from cleaned payee, account, date & amount."""
    print("\n--- Training Model 3: Category Classifier ---")
    df_valid = df[(df["is_transfer"] == False) & df["category_id"].notna() & (df["category_id"] != "")].copy()
    
    X = df_valid[["cleaned_payee", "account_id", "amount_log", "amount_sign", "day_of_week", "day_of_month", "month"]]
    y = df_valid["category_id"]

    counts = y.value_counts()
    stratify = y if counts.min() >= 2 else None

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=stratify
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("text", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True, token_pattern=r"\b\w+\b"), "cleaned_payee"),
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["account_id"]),
            ("num", StandardScaler(), ["amount_log", "amount_sign", "day_of_week", "day_of_month", "month"])
        ]
    )

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", LogisticRegression(max_iter=1000, C=10.0, class_weight="balanced"))
        ]
    )

    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    print(f"✓ Category Classifier Accuracy (validation set): {acc * 100:.2f}%")

    # Fit final model on full dataset for maximum vocabulary and class coverage
    pipeline.fit(X, y)

    return pipeline, preprocessor

def train_all_models():
    df = load_dataset()
    df = preprocess_dataframe(df)

    payee_pipeline, _ = train_payee_resolver(df)
    category_pipeline, _ = train_category_classifier(df)

    return df, payee_pipeline, category_pipeline

if __name__ == "__main__":
    train_all_models()
