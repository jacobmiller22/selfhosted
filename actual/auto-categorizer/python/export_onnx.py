import json
from datetime import datetime
from pathlib import Path
import numpy as np
from skl2onnx import to_onnx
from skl2onnx.common.data_types import StringTensorType, FloatTensorType
from sklearn.linear_model import LogisticRegression

from train import train_all_models
from config import MODELS_DIR

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

    manifest = {
        "timestamp": datetime.now().isoformat(),
        "models": {
            "payee_resolver": {
                "file": "payee_resolver.onnx",
                "classes": payee_classes
            },
            "category_classifier": {
                "file": "category_classifier.onnx",
                "classes": category_classes
            }
        }
    }

    manifest_path = MODELS_DIR / "model_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"✓ Saved manifest metadata -> {manifest_path}")

if __name__ == "__main__":
    export_all()
