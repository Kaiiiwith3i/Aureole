"""Change-region classifier: features -> trained RandomForest (models/change_clf.joblib) or heuristic fallback."""
import numpy as np

from core.diff import Region

LABELS = ["stamp", "handwriting", "physical_damage", "fold", "text_change", "unknown"]

# Order is the model's input order. Builders may append features but must keep this list in sync with extract_features.
FEATURE_NAMES = [
    "hue_mean", "hue_std", "sat_mean", "sat_std", "val_mean",  # color stats of changed pixels in the scan (HSV)
    "edge_density", "stroke_width", "circularity", "aspect_ratio", "extent",
    "area", "bbox_w", "bbox_h", "contrast", "added", "ela_mean", "zone_overlap",
]


def extract_features(aligned: np.ndarray, expected: np.ndarray, region: Region, zone_bboxes: list[list[int]], ela: np.ndarray | None = None) -> np.ndarray:
    """float32 vector, len(FEATURE_NAMES). `ela` is a gray uint8 ELA map in template space (or None -> ela_mean 0).
    zone_overlap = share of the region bbox that lies inside any protected zone bbox. Must be cheap (< 5 ms per region)."""
    raise NotImplementedError


def heuristic_classify(features: np.ndarray) -> tuple[str, float]:
    """Rule-based (label, confidence 0..1). Used when the model file is missing."""
    raise NotImplementedError


def classify(features: np.ndarray) -> tuple[str, float]:
    """(label in LABELS, confidence 0..1). Uses the joblib model at core.MODEL_PATH when present (load once, cache),
    confidence = max predict_proba. The file holds {"model": estimator, "features": FEATURE_NAMES, "labels": [...]};
    if it is missing or its feature list differs from FEATURE_NAMES, log a warning once and use heuristic_classify."""
    raise NotImplementedError
