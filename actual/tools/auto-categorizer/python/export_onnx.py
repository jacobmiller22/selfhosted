import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from skl2onnx import to_onnx
from skl2onnx.common.data_types import StringTensorType, FloatTensorType
from sklearn.linear_model import LogisticRegression

from train import train_all_models
from config import MODELS_DIR, DATA_DIR, BASE_DIR

def compute_hidden_to_active_map(df: pd.DataFrame) -> dict:
    """Infer transition map from historical hidden/deprecated categories to active categories."""
    mapping = {}

    db_path = DATA_DIR / "latest_db.sqlite"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        cats = dict(conn.execute("SELECT id, name FROM categories").fetchall())
        active_cats = {r[1]: r[0] for r in conn.execute("SELECT id, name FROM categories WHERE hidden = 0 AND tombstone = 0").fetchall()}

        # Known direct consolidations
        known_remaps = {
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
        for name, active_id in known_remaps.items():
            if active_id:
                for h_id, h_name in cats.items():
                    if h_name == name and h_id != active_id:
                        mapping[h_id] = active_id

    # Fallback to shared non-empty payee co-occurrence for any remaining hidden categories
    if not df.empty and "category_id" in df.columns and "cleaned_payee" in df.columns:
        df_calc = df[df["cleaned_payee"].str.strip() != ""].copy()
        dates = pd.to_datetime(df_calc["date"], errors="coerce")
        max_date = dates.max()
        if pd.notna(max_date):
            days_old = (max_date - dates).dt.total_seconds() / 86400.0
            df_calc["weight"] = np.exp(-(np.log(2.0) / 180.0) * days_old.fillna(0.0).clip(lower=0.0))
            recent_cutoff = max_date - pd.Timedelta(days=180)
            cats_recent = set(df_calc[pd.to_datetime(df_calc["date"]) >= recent_cutoff]["category_id"].dropna().unique())
            cats_all = set(df_calc["category_id"].dropna().unique())
            hidden_candidates = (cats_all - cats_recent) - set(mapping.keys())

            for h_cat in hidden_candidates:
                h_payees = df_calc[df_calc["category_id"] == h_cat]["cleaned_payee"].unique()
                h_payees = [p for p in h_payees if p]
                if not h_payees:
                    continue
                matched_active = df_calc[(df_calc["cleaned_payee"].isin(h_payees)) & (df_calc["category_id"].isin(cats_recent))]
                if not matched_active.empty:
                    best_cat = matched_active.groupby("category_id")["weight"].sum().idxmax()
                    mapping[h_cat] = str(best_cat)

    return mapping

def export_pipeline_to_onnx(pipeline, initial_types, onnx_filename: str) -> Path:
    """Convert Scikit-learn Pipeline to ONNX format using skl2onnx with zipmap=False for ONNX Tensor output."""
    options = {LogisticRegression: {"zipmap": False}}
    onnx_model = to_onnx(
        pipeline,
        initial_types=initial_types,
        target_opset=15,
        options=options
    )

    out_path = MODELS_DIR / onnx_filename
    with open(out_path, "wb") as f:
        f.write(onnx_model.SerializeToString())

    print(f"✓ Exported ONNX model -> {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
    return out_path

def export_all():
    print("Starting Model Training & ONNX Export Pipeline (zipmap=False)...")
    df, payee_pipeline, category_pipeline = train_all_models()

    # Define ONNX input shapes & types for Payee Resolver
    payee_initial_types = [
        ("cleaned_payee", StringTensorType([None, 1])),
        ("account_id", StringTensorType([None, 1])),
        ("persona", StringTensorType([None, 1])),
        ("amount_log", FloatTensorType([None, 1])),
        ("amount_sign", FloatTensorType([None, 1]))
    ]

    export_pipeline_to_onnx(payee_pipeline, payee_initial_types, "payee_resolver.onnx")

    # Define ONNX input shapes & types for Category Classifier
    category_initial_types = [
        ("cleaned_payee", StringTensorType([None, 1])),
        ("account_id", StringTensorType([None, 1])),
        ("persona", StringTensorType([None, 1])),
        ("amount_log", FloatTensorType([None, 1])),
        ("amount_sign", FloatTensorType([None, 1])),
        ("day_of_week", FloatTensorType([None, 1])),
        ("day_of_month", FloatTensorType([None, 1])),
        ("month", FloatTensorType([None, 1]))
    ]

    export_pipeline_to_onnx(category_pipeline, category_initial_types, "category_classifier.onnx")

    # Export label mapping manifest
    payee_classes = payee_pipeline.classes_.tolist()
    category_classes = category_pipeline.classes_.tolist()
    hidden_to_active_map = compute_hidden_to_active_map(df)

    manifest = {
        "timestamp": datetime.now().isoformat(),
        "half_life_days": 180.0,
        "models": {
            "payee_resolver": {
                "file": "payee_resolver.onnx",
                "classes": payee_classes
            },
            "category_classifier": {
                "file": "category_classifier.onnx",
                "classes": category_classes
            }
        },
        "hidden_to_active_map": hidden_to_active_map
    }

    manifest_path = MODELS_DIR / "model_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"✓ Saved manifest metadata with {len(hidden_to_active_map)} inferred category mappings -> {manifest_path}")

    # Copy exported models to sidecar models dir and top-level models dir
    sidecar_models_dir = BASE_DIR.parent / "src" / "models"
    toplevel_models_dir = BASE_DIR.parent.parent.parent / "auto-categorizer-models"

    for dest_dir in [sidecar_models_dir, toplevel_models_dir]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(manifest_path, dest_dir / "model_manifest.json")
        shutil.copy(MODELS_DIR / "payee_resolver.onnx", dest_dir / "payee_resolver.onnx")
        shutil.copy(MODELS_DIR / "category_classifier.onnx", dest_dir / "category_classifier.onnx")
        print(f"✓ Synced models to {dest_dir}")

if __name__ == "__main__":
    export_all()
