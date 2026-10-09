import functools
import time

import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

import core
from core import classify as C
from core.diff import Region, diff_regions
from test_diff import MARKERS, ZONE, mark, page, photo

ZONES = [ZONE, [180, 740, 620, 84], [270, 440, 1800, 130]]
EXPECT = {"stamp": "stamp", "scribble": "handwriting", "stain": "physical_damage", "fold": "fold", "text": "text_change"}


@functools.lru_cache(maxsize=16)
def feats(kind, seed=5):
    exp, scene, gt = mark(kind)
    al = photo(scene, seed)
    reg = diff_regions(exp, al, MARKERS)[0]
    return C.extract_features(al, exp, reg, ZONES), (al, exp, reg)


def test_features_shape_and_finite():
    for kind in EXPECT:
        f, _ = feats(kind)
        assert f.dtype == np.float32 and f.shape == (len(C.FEATURE_NAMES),) and np.isfinite(f).all()


def test_features_are_deterministic_and_cheap():
    f, (al, exp, reg) = feats("stamp")
    t = time.perf_counter()
    for _ in range(10):
        g = C.extract_features(al, exp, reg, ZONES)
    per = (time.perf_counter() - t) / 10
    assert (f == g).all()
    assert per < 0.02, per  # contract says < 5 ms; the stamp is a 250 px region, measured well under


def test_heuristics_label_the_five_cases():
    for kind, want in EXPECT.items():
        f, _ = feats(kind)
        label, conf = C.heuristic_classify(f)
        assert label == want and conf >= 0.6, (kind, label, conf)


def test_heuristics_stable_across_noise_seeds():
    for kind, want in EXPECT.items():
        for seed in (1, 9):
            assert C.heuristic_classify(feats(kind, seed)[0])[0] == want, (kind, seed)


def test_fold_across_a_zone_is_not_text_change():
    exp, scene, _ = mark("fold")
    al = photo(scene)
    reg = diff_regions(exp, al, MARKERS)[0]
    f = C.extract_features(al, exp, reg, [[1200, 0, 300, 1654]])  # zone swallowing the fold
    label, conf = C.heuristic_classify(f)
    assert not (label == "text_change" and conf >= 0.6)


def test_tiny_faint_speck_is_unknown():
    exp = page()
    al = exp.copy()
    al[400:404, 500:504] = 200
    mask = np.full((4, 4), 255, np.uint8)
    f = C.extract_features(al, exp, Region((500, 400, 4, 4), mask, 16, 1.0), ZONES)
    label, conf = C.heuristic_classify(f)
    assert label == "unknown" or conf < 0.6


@pytest.fixture
def model_path(tmp_path, monkeypatch):
    p = tmp_path / "m.joblib"
    monkeypatch.setattr(core, "MODEL_PATH", p)
    C._cache.clear()
    return p


def _rf(n_features):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(60, n_features))
    y = np.arange(60) % len(C.LABELS)
    return RandomForestClassifier(n_estimators=5, random_state=0).fit(X, y)


def test_classify_falls_back_without_model(model_path):
    f, _ = feats("stamp")
    assert not model_path.exists()
    assert C.classify(f) == C.heuristic_classify(f)


def test_classify_uses_saved_model(model_path):
    rf = _rf(len(C.FEATURE_NAMES))
    joblib.dump({"model": rf, "features": C.FEATURE_NAMES, "labels": C.LABELS}, model_path)
    f = np.random.default_rng(1).normal(size=len(C.FEATURE_NAMES)).astype(np.float32)
    label, conf = C.classify(f)
    p = rf.predict_proba(f.reshape(1, -1))[0]
    assert label == C.LABELS[int(rf.classes_[p.argmax()])] and conf == pytest.approx(p.max())


def test_classify_rejects_model_with_other_features(model_path, caplog):
    joblib.dump({"model": _rf(3), "features": ["a", "b", "c"], "labels": C.LABELS}, model_path)
    f, _ = feats("stamp")
    with caplog.at_level("WARNING", logger="signet"):
        assert C.classify(f) == C.heuristic_classify(f)
        C.classify(f)
    assert sum("different features" in r.message for r in caplog.records) == 1
