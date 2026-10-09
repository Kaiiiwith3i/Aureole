"""Change-region classifier: features -> trained RandomForest (models/change_clf.joblib) or heuristic fallback."""
import math

import cv2
import joblib
import numpy as np

import core
from core.diff import Region

LABELS = ["stamp", "handwriting", "physical_damage", "fold", "text_change", "unknown"]

# Order is the model's input order. Builders may append features but must keep this list in sync with extract_features.
FEATURE_NAMES = [
    "hue_mean", "hue_std", "sat_mean", "sat_std", "val_mean",  # color stats of changed pixels in the scan (HSV)
    "edge_density", "stroke_width", "circularity", "aspect_ratio", "extent",
    "area", "bbox_w", "bbox_h", "contrast", "added", "ela_mean", "zone_overlap",
]


_MAXSIDE = 256  # crops are shrunk to this before pixel statistics, so cost does not grow with region size
_CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)


def extract_features(aligned: np.ndarray, expected: np.ndarray, region: Region, zone_bboxes: list[list[int]], ela: np.ndarray | None = None) -> np.ndarray:
    """float32 vector, len(FEATURE_NAMES). `ela` is a gray uint8 ELA map in page space (or None -> ela_mean 0).
    zone_overlap = share of the region bbox that lies inside any protected zone bbox. Must be cheap (< 5 ms per region)."""
    x, y, w, h = region.bbox
    s = max(1, math.ceil(max(w, h) / _MAXSIDE))
    a, e, mk = aligned[y:y + h, x:x + w], expected[y:y + h, x:x + w], region.mask
    if s > 1:
        sz = (max(w // s, 1), max(h // s, 1))
        a, e = cv2.resize(a, sz, interpolation=cv2.INTER_AREA), cv2.resize(e, sz, interpolation=cv2.INTER_AREA)
        mk = cv2.resize(mk, sz, interpolation=cv2.INTER_AREA)  # any coverage counts, so hairlines survive
    ms = mk > 0
    ga, ge = _gray(a), _gray(e)
    paper_a, paper_e = max(float(np.percentile(ga[::2, ::2], 90)), 30.0), max(float(np.percentile(ge[::2, ::2], 90)), 30.0)
    n = int(ms.sum())
    if n == 0:  # mask vanished in the shrink
        ms = np.ones_like(ms)
        n = ms.size
    # --- color of the changed pixels in the scan; near-black ink is skipped because its hue/sat is noise
    px = a[ms]
    px = px[:: max(1, len(px) // 1500)]
    hsv = cv2.cvtColor(px.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    keep = hsv[:, 2] >= 0.4 * paper_a
    hue_mean = hue_std = sat_mean = sat_std = 0.0
    if keep.any():
        hh, ss = hsv[keep, 0] * (math.pi / 90), hsv[keep, 1] / 255
        sat_mean, sat_std = float(ss.mean()), float(ss.std())
        if ss.sum() > 1e-3:  # saturation-weighted circular mean of hue (OpenCV units 0..180; red wraps)
            c, sn = (ss * np.cos(hh)).sum(), (ss * np.sin(hh)).sum()
            hue_mean = (math.atan2(sn, c) % (2 * math.pi)) * 90 / math.pi
            hue_std = 1 - math.hypot(c, sn) / ss.sum()
    val_mean = float(min(hsv[:, 2].mean() / paper_a, 2.0))
    # --- geometry
    gx, gy = cv2.Sobel(ga, cv2.CV_32F, 1, 0), cv2.Sobel(ga, cv2.CV_32F, 0, 1)
    edge_density = float(cv2.magnitude(gx, gy)[ms].mean() / paper_a)
    perim = max(cv2.countNonZero(region.mask) - cv2.countNonZero(cv2.erode(region.mask, _CROSS)), 1)
    stroke_width = 2.0 * region.area / perim  # exact for a stroke of constant width
    pts = cv2.findNonZero(ms.astype(np.uint8))
    hull = cv2.convexHull(pts)
    hp = cv2.arcLength(hull, True) * s
    circularity = min(4 * math.pi * cv2.contourArea(hull) * s * s / (hp * hp), 1.0) if hp > 1 else 0.0
    ev = np.linalg.eigvalsh(np.cov(pts.reshape(-1, 2).T.astype(np.float64) * s)) if len(pts) > 2 else np.array([0.0, 1.0])
    aspect_ratio = min(math.sqrt(max(ev[1], 1.0) / max(ev[0], 1.0)), 60.0)
    contrast = float(ge[ms].mean() / paper_e - ga[ms].mean() / paper_a)  # > 0: scan is darker than expected
    ela_mean = float(ela[y:y + h:s, x:x + w:s].mean() / 255) if ela is not None else 0.0
    zone = sum(max(0, min(x + w, zx + zw) - max(x, zx)) * max(0, min(y + h, zy + zh) - max(y, zy)) for zx, zy, zw, zh in zone_bboxes)
    v = [hue_mean, hue_std, sat_mean, sat_std, val_mean, edge_density, stroke_width, circularity, aspect_ratio,
         region.area / max(w * h, 1), region.area, w, h, contrast, region.added, ela_mean, min(zone / max(w * h, 1), 1.0)]
    return np.nan_to_num(np.array(v, np.float32), nan=0.0, posinf=0.0, neginf=0.0)


def heuristic_classify(features: np.ndarray) -> tuple[str, float]:
    """Rule-based (label, confidence 0..1). Used when the model file is missing."""
    f = dict(zip(FEATURE_NAMES, (float(v) for v in features)))
    hue, sat, w, h = f["hue_mean"], f["sat_mean"], f["bbox_w"], f["bbox_h"]
    big, thin = min(w, h), min(w, h) <= 40
    if f["area"] < 150 or max(w, h) < 20:
        return "unknown", 0.2
    # long thin line (a fold has a shading band but its dark core is what the diff sees); beats everything, incl. zones
    if sat < 0.12 and f["aspect_ratio"] >= 25 and (thin or f["aspect_ratio"] >= 40):
        return "fold", 0.8
    if sat >= 0.12:
        red, blue, brown = hue < 12 or hue > 165, 90 <= hue <= 135, 8 <= hue <= 38
        if red and f["circularity"] > 0.7 and big > 100:
            return "stamp", 0.85
        if blue and not f["circularity"] > 0.9:
            return "handwriting", 0.8
        if brown and sat < 0.7 and big > 60:
            return "physical_damage", 0.75
        if red and f["circularity"] <= 0.7:
            return "handwriting", 0.6  # red pen
        return "unknown", 0.4
    # achromatic from here
    if f["zone_overlap"] >= 0.5 and h <= 200 and not f["circularity"] > 0.85:
        return "text_change", 0.8 if f["added"] < 0.9 else 0.55  # pure added ink is ambiguous: stay under the 0.6 verdict line
    if big > 100 and f["circularity"] > 0.85:
        return "physical_damage", 0.6
    return "unknown", 0.35


_cache: dict = {}  # path -> (mtime_ns, estimator, labels) or (mtime_ns, None, None) after a warning


def _load():
    path = core.MODEL_PATH
    try:
        mt = path.stat().st_mtime_ns
    except OSError:
        mt = None
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return hit[1], hit[2]
    model = labels = None
    if mt is None:
        core.log.warning("classifier model %s not found, using heuristics", path)
    else:
        try:
            blob = joblib.load(path)
            if list(blob["features"]) == FEATURE_NAMES:
                model, labels = blob["model"], list(blob["labels"])
            else:
                core.log.warning("classifier model %s was trained on different features, using heuristics", path)
        except Exception as exc:  # corrupt/unpicklable file must not break verification
            core.log.warning("classifier model %s unusable (%s), using heuristics", path, exc)
    _cache[path] = (mt, model, labels)
    return model, labels


def classify(features: np.ndarray) -> tuple[str, float]:
    """(label in LABELS, confidence 0..1). Uses the joblib model at core.MODEL_PATH when present (load once, cache),
    confidence = max predict_proba. The file holds {"model": estimator, "features": FEATURE_NAMES, "labels": [...]};
    if it is missing or its feature list differs from FEATURE_NAMES, log a warning once and use heuristic_classify."""
    model, labels = _load()
    if model is None:
        return heuristic_classify(features)
    proba = model.predict_proba(np.asarray(features, np.float32).reshape(1, -1))[0]
    k = int(np.argmax(proba))
    cls = model.classes_[k]
    label = labels[int(cls)] if isinstance(cls, (int, np.integer)) else str(cls)
    return label, float(proba[k])
