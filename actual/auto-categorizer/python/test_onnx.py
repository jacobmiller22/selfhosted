import json
import math
import numpy as np
import onnxruntime as ort
from config import MODELS_DIR
from text_cleaner import clean_payee_text

def test_onnx_models():
    manifest_path = MODELS_DIR / "model_manifest.json"
    assert manifest_path.exists(), f"Manifest {manifest_path} does not exist"

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    print("\n--- Testing ONNX Model Loading & Inference ---")

    # 1. Test Payee Resolver ONNX Model
    payee_onnx_path = MODELS_DIR / manifest["models"]["payee_resolver"]["file"]
    
    session_payee = ort.InferenceSession(str(payee_onnx_path))
    print(f"✓ Loaded {payee_onnx_path.name} into ONNX Runtime")

    # Raw bank payee string: "SQ *TRADER JOE'S #521 SAN FRANCISCO CA"
    raw_tj = "SQ *TRADER JOE'S #521 SAN FRANCISCO CA"
    clean_tj = clean_payee_text(raw_tj)

    tj_cents = 6500  # $65.00
    tj_amount_log = float(math.log1p(tj_cents))

    inputs_payee = {
        "cleaned_payee": np.array([[clean_tj]], dtype=object),
        "account_id": np.array([["acct_credit_card"]], dtype=object),
        "amount_log": np.array([[tj_amount_log]], dtype=np.float32),
        "amount_sign": np.array([[-1.0]], dtype=np.float32)
    }

    outputs_payee = session_payee.run(None, inputs_payee)
    predicted_payee = outputs_payee[0][0]
    payee_probs = outputs_payee[1][0]
    top_payee_prob = payee_probs.get(predicted_payee, 0.0)

    print(f"  Raw Input:       '{raw_tj}' ($65.00)")
    print(f"  Cleaned Text:    '{clean_tj}'")
    print(f"  Predicted Payee: '{predicted_payee}' (Confidence: {top_payee_prob * 100:.1f}%)\n")

    # 2. Test Category Classifier ONNX Model
    cat_onnx_path = MODELS_DIR / manifest["models"]["category_classifier"]["file"]
    session_cat = ort.InferenceSession(str(cat_onnx_path))
    print(f"✓ Loaded {cat_onnx_path.name} into ONNX Runtime")

    raw_sb = "SQ *STARBUCKS COFFEE #08492"
    clean_sb = clean_payee_text(raw_sb)

    sb_cents = 550  # $5.50
    sb_amount_log = float(math.log1p(sb_cents))

    inputs_cat = {
        "cleaned_payee": np.array([[clean_sb]], dtype=object),
        "account_id": np.array([["acct_credit_card"]], dtype=object),
        "amount_log": np.array([[sb_amount_log]], dtype=np.float32),
        "amount_sign": np.array([[-1.0]], dtype=np.float32),
        "day_of_week": np.array([[2.0]], dtype=np.float32),
        "day_of_month": np.array([[15.0]], dtype=np.float32),
        "month": np.array([[9.0]], dtype=np.float32)
    }

    outputs_cat = session_cat.run(None, inputs_cat)
    predicted_cat = outputs_cat[0][0]
    cat_probs = outputs_cat[1][0]
    top_cat_prob = cat_probs.get(predicted_cat, 0.0)

    print(f"  Raw Input:          '{raw_sb}' ($5.50)")
    print(f"  Cleaned Text:       '{clean_sb}'")
    print(f"  Predicted Category: '{predicted_cat}' (Confidence: {top_cat_prob * 100:.1f}%)")

    print("\n🎉 ONNX Runtime Model Verification Successful!")

if __name__ == "__main__":
    test_onnx_models()
