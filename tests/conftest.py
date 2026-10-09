import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    """Every test gets its own SIGNET_DATA_DIR so nothing touches runtime/."""
    monkeypatch.setenv("SIGNET_DATA_DIR", str(tmp_path / "data"))
