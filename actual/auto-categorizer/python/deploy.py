import argparse
import json
import shutil
from pathlib import Path
import requests

from config import MODELS_DIR

def deploy_to_local_directory(target_path: Path):
    """Copy exported ONNX models and manifest to a local directory (e.g. sidecar src/models)."""
    target_path = Path(target_path).resolve()
    target_path.mkdir(parents=True, exist_ok=True)

    manifest_file = MODELS_DIR / "model_manifest.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"Model manifest not found at {manifest_file}. Please run export_onnx.py first.")

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    shutil.copy(manifest_file, target_path / "model_manifest.json")
    print(f"✓ Copied manifest -> {target_path / 'model_manifest.json'}")

    for model_name, model_info in manifest["models"].items():
        filename = model_info["file"]
        src_file = MODELS_DIR / filename
        if src_file.exists():
            shutil.copy(src_file, target_path / filename)
            print(f"✓ Copied {filename} -> {target_path / filename}")
        else:
            print(f"⚠️ Warning: Model file {src_file} does not exist.")

    print(f"🎉 Model deployment complete to local directory: {target_path}")

def deploy_to_remote_sidecar(sidecar_url: str, api_token: str = None):
    """Upload models to remote sidecar daemon via HTTP upload endpoint."""
    manifest_file = MODELS_DIR / "model_manifest.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"Model manifest not found at {manifest_file}. Please run export_onnx.py first.")

    upload_url = f"{sidecar_url.rstrip('/')}/api/models/upload"
    headers = {}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    print(f"Uploading models to {upload_url}...")
    files = {
        "manifest": ("model_manifest.json", open(manifest_file, "rb"), "application/json"),
        "payee_resolver": ("payee_resolver.onnx", open(MODELS_DIR / "payee_resolver.onnx", "rb"), "application/octet-stream"),
        "category_classifier": ("category_classifier.onnx", open(MODELS_DIR / "category_classifier.onnx", "rb"), "application/octet-stream")
    }

    try:
        response = requests.post(upload_url, files=files, headers=headers)
        response.raise_for_status()
        print(f"✓ Upload successful! Response: {response.json()}")
    except Exception as e:
        print(f"❌ Failed to upload models: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy trained ONNX models to local directory or sidecar daemon.")
    parser.add_argument("--local-dir", type=str, help="Target local directory path to copy models into")
    parser.add_argument("--sidecar-url", type=str, help="Sidecar REST endpoint URL")
    parser.add_argument("--token", type=str, help="Optional API token for sidecar authentication")

    args = parser.parse_args()

    if args.local_dir:
        deploy_to_local_directory(Path(args.local_dir))
    elif args.sidecar_url:
        deploy_to_remote_sidecar(args.sidecar_url, args.token)
    else:
        # Default fallback: deploy to relative sidecar models directory
        default_target = Path(__file__).resolve().parent.parent / "src" / "models"
        deploy_to_local_directory(default_target)
