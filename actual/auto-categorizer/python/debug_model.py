import json
import numpy as np
import pandas as pd
import onnxruntime as ort
from train import train_all_models, preprocess_dataframe

df, payee_pipeline, category_pipeline = train_all_models()

# Sample test data
test_df = pd.DataFrame([{
    "imported_payee": "trader joes #521 san francisco",
    "account_id": "acct_credit_card",
    "amount": -6500,  # $65.00 -> log1p(6500) = 8.779
    "date": "2026-09-08"
}])
test_df = preprocess_dataframe(test_df)

X = test_df[["imported_payee", "account_id", "amount_log", "amount_sign"]]
sklearn_pred = payee_pipeline.predict(X)
sklearn_proba = payee_pipeline.predict_proba(X)

print("\n=== SKLEARN PREDICTION ===")
print("Classes:", payee_pipeline.classes_)
print("Predicted Class:", sklearn_pred[0])
print("Probabilities:", dict(zip(payee_pipeline.classes_, sklearn_proba[0])))

# Test ONNX model
sess = ort.InferenceSession("models/payee_resolver.onnx")
inputs = {
    "imported_payee": np.array([["trader joes #521 san francisco"]], dtype=object),
    "account_id": np.array([["acct_credit_card"]], dtype=object),
    "amount_log": np.array([[test_df["amount_log"].values[0]]], dtype=np.float32),
    "amount_sign": np.array([[-1.0]], dtype=np.float32)
}
onnx_outputs = sess.run(None, inputs)

print("\n=== ONNX OUTPUTS ===")
print("Output 0 (Label):", onnx_outputs[0])
print("Output 1 (Probabilities):", onnx_outputs[1])
