"""The generated v2 demo must verify against the registry it just created."""
import joblib
import pytest

import core
from devtools.demo_set import build_demo_set
from core import pipeline


def test_demo_verdicts(tmp_path):
    if not core.MODEL_PATH.exists() or joblib.load(core.MODEL_PATH).get("training") != "v2-issued-pages":
        pytest.skip("run scripts/train_classifier.py before the model-backed demo check")
    expected = build_demo_set(tmp_path)
    assert len(expected) == 10
    for name, want in expected.items():
        report = pipeline.verify([(name, (tmp_path / name).read_bytes())])
        assert report.verdict == want["verdict"], (name, report.verdict, report.headline)
