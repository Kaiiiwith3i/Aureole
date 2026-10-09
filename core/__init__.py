"""Signet core. Shared paths and logger live here so no module needs a config file."""
import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS_DIR = ROOT / "keys"
FONTS_DIR = ROOT / "assets" / "fonts"
MODEL_PATH = ROOT / "models" / "change_clf.joblib"

log = logging.getLogger("signet")


def data_dir() -> Path:
    """Everything mutable (registry DB, reports, issued files). Read the env var on every call so tests can redirect it."""
    d = Path(os.environ.get("SIGNET_DATA_DIR") or ROOT / "runtime")
    d.mkdir(parents=True, exist_ok=True)
    return d
