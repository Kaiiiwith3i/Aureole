"""Builds the 10 demo files + expected.json. Sealed documents are issued through core.pipeline into data_dir()."""
from pathlib import Path


def build_demo_set(out_dir: Path) -> dict:
    """Write 01_genuine.png ... 10_no_seal_edited.jpg and expected.json into out_dir; return the expected dict.

    expected.json: {"<file>": {"verdict": str, "field_status": {key: status} (only what must be asserted),
                               "finding_types": [types that must appear], "critical_field": key | null,
                               "current_version": int | null, "min_findings": int}}
    """
    raise NotImplementedError
