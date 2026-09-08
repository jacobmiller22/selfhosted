import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from python/ or parent directory
BASE_DIR = Path(__file__).resolve().parent
PARENT_DIR = BASE_DIR.parent

load_dotenv(BASE_DIR / ".env")
load_dotenv(PARENT_DIR / ".env")

ACTUAL_SERVER_URL = os.getenv("ACTUAL_SERVER_URL", "http://localhost:5006")
ACTUAL_PASSWORD = os.getenv("ACTUAL_PASSWORD", "")
ACTUAL_SYNC_ID = os.getenv("ACTUAL_SYNC_ID", "")

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
MODELS_DIR = Path(os.getenv("MODELS_DIR", BASE_DIR / "models"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
