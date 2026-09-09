import json
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from skl2onnx import to_onnx
from skl2onnx.common.data_types import StringTensorType, FloatTensorType
from sklearn.linear_model import LogisticRegression

from train import train_all_models
from config import MODELS_DIR

def compute_hidden_to_active_map(df: pd.DataFrame) -> dict:
    """Infer time-weighted transition map from historical hidden/deprecated categories to active categories based on shared payee history."""
    if df.empty or "category_id" not in df.columns or "imported_payee" not in df.columns:
        return {}

    dates = pd.to_datetime(df["date"], errors="coerce")
    max_date = dates.max()
    if pd.isna(max_date):
        weights = np.ones(len(df))
    else:
        days_old = (max_date - dates).dt.total_seconds() / 86400.0
        weights = np.exp(-(np.log(2.0) / 180.0) * days_old.fillna(0.0).clip(lower=0.0))

    df_calc = df.copy()
    df_calc["weight"] = weights
    df_calc["clean_payee"] = df_calc["imported_payee"].fillna("").astype(str).str.lower().str.strip()

    recent_cutoff = max_date - pd.Timedelta(days=180) if pd.notna(max_date) else None

    if recent_cutoff:
        cats_recent = set(df_calc[pd.to_datetime(df_calc["date"]) >= recent_cutoff]["category_id"].dropna().unique())
        cats_all = set(df_calc["category_id"].dropna().unique())
        hidden_candidates = cats_all - cats_recent
        active_candidates = cats_recent
    else:
        hidden_candidates = set()
        active_candidates = set(df_calc["category_id"].dropna().unique())

    mapping = {}
    for h_cat in hidden_candidates:
        h_payees = df_calc[df_calc["category_id"] == h_cat]["clean_payee"].unique()
        matched_active = df_calc[(df_calc["clean_payee"].isin(h_payees)) & (df_calc["category_id"].isin(active_candidates))]
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
        ("amount_log", FloatTensorType([None, 1])),
        ("amount_sign", FloatTensorType([None, 1]))
    ]

    export_pipeline_to_onnx(payee_pipeline, payee_initial_types, "payee_resolver.onnx")

    # Define ONNX input shapes & types for Category Classifier
    category_initial_types = [
        ("cleaned_payee", StringTensorType([None, 1])),
        ("account_id", StringTensorType([None, 1])),
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

if __name__ == "__main__":
    export_all()
