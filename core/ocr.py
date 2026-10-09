"""OCR engine wrapper. RapidOCR (ONNX, on-device); EasyOCR only as an import fallback. Lazy singleton."""
import logging
import threading
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

import cv2
import numpy as np

_PAD = 12  # px of white kept around the ink box
_MIN_INK = 30  # fewer dark pixels than this = blank zone

_lock = threading.Lock()
_engine = None  # (name, callable(bgr, det: bool) -> (texts, scores))


@dataclass
class OcrResult:
    text: str  # "" when nothing was read
    confidence: float  # 0..1; 0.0 when nothing was read


def _pkg_version(*names: str) -> str:
    for n in names:
        try:
            return version(n)
        except PackageNotFoundError:
            pass
    return "?"


def _load():
    """Return (name, fn). fn(bgr, det) -> (list[str], list[float])."""
    global _engine
    if _engine:
        return _engine
    for mod in ("rapidocr", "rapidocr_onnxruntime"):
        try:
            RapidOCR = __import__(mod, fromlist=["RapidOCR"]).RapidOCR
        except ImportError:
            continue
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        logging.getLogger(mod).setLevel(logging.ERROR)
        eng = RapidOCR(params={"Global.log_level": "error"}) if mod == "rapidocr" else RapidOCR()

        def run(bgr, det, eng=eng, boxes=False):
            if mod == "rapidocr":
                o = eng(bgr, use_det=det, use_cls=False)
                t, s = list(o.txts or ()), list(o.scores or ())
                return (t, s, o.boxes if o.boxes is not None else []) if boxes else (t, s)
            res, _ = eng(bgr, use_det=det, use_cls=False)  # legacy: [[box, text, score]]
            res = res or []
            t, s = [r[-2] for r in res], [float(r[-1]) for r in res]
            return (t, s, [r[0] for r in res]) if boxes else (t, s)

        _engine = (f"rapidocr {_pkg_version('rapidocr', 'rapidocr_onnxruntime')} (onnxruntime)", run)
        return _engine
    try:
        import easyocr
    except ImportError:
        raise RuntimeError("No OCR engine installed: need rapidocr, rapidocr_onnxruntime or easyocr") from None
    reader = easyocr.Reader(["en"], gpu=False)  # ponytail: untested fallback, may download models
    _engine = (f"easyocr {_pkg_version('easyocr')}",
               lambda bgr, det, boxes=False: (lambda r: ([t for _, t, _ in r], [c for _, _, c in r])
                                              + (([b for b, _, _ in r],) if boxes else ()))(reader.readtext(bgr)))
    return _engine


def engine_name() -> str:
    """e.g. "rapidocr 3.10.0 (onnxruntime)". Must not trigger model loading."""
    if _engine:
        return _engine[0]
    for names in (("rapidocr",), ("rapidocr_onnxruntime",), ("easyocr",)):
        if (v := _pkg_version(*names)) != "?":
            return f"{names[0]} {v}" + ("" if names[0] == "easyocr" else " (onnxruntime)")
    return "none"


def warm_up() -> None:
    """Load the models and run one tiny inference so the first real call is fast."""
    img = np.full((100, 300, 3), 255, np.uint8)
    cv2.putText(img, "Warm 123", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
    with _lock:
        run = _load()[1]
        run(img, False)
        run(img, True)


def _ink_box(gray: np.ndarray):
    """Bounding box (x0, y0, x1, y1) of dark pixels (Otsu on the crop), or None if the crop is blank."""
    t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Otsu on a near-blank crop picks noise: require real contrast too.
    if gray.max() - gray.min() < 60:
        return None
    mask = gray < min(t, 160)
    if mask.sum() < _MIN_INK:
        return None
    ys, xs = np.where(mask)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def read_text(image: np.ndarray) -> OcrResult:
    """Read ONE line of text from a BGR crop of a field zone (text plus white margin, any width).
    Several text boxes -> join left-to-right with single spaces; confidence = the lowest box score.
    Thread-safe (the API calls this from a threadpool). Never touches the network."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    box = _ink_box(gray)
    if box is None:
        return OcrResult("", 0.0)
    x0, y0, x1, y1 = box
    h, w = gray.shape
    crop = image[max(0, y0 - _PAD):min(h, y1 + _PAD), max(0, x0 - _PAD):min(w, x1 + _PAD)]
    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    with _lock:
        run = _load()[1]
        for det in (False, True):  # recognition-only first (fast); detection as fallback
            txts, scores = run(crop, det)
            txts = [t.strip() for t in txts]
            if any(txts):
                break
    if not any(txts):
        return OcrResult("", 0.0)
    return OcrResult(" ".join(t for t in txts if t), float(min(s for t, s in zip(txts, scores) if t)))


@dataclass
class OcrLine:
    bbox: list[int]  # [x, y, w, h] image px, axis-aligned around the detected quad
    text: str
    confidence: float


def read_lines(image: np.ndarray) -> list[OcrLine]:
    """Detect and read every text line of a BGR image, top-to-bottom then left-to-right. [] when nothing is read."""
    with _lock:
        txts, scores, boxes = _load()[1](image, True, boxes=True)
    out = []
    for t, s, b in zip(txts, scores, boxes):
        b = np.asarray(b, float).reshape(-1, 2)
        x0, y0 = np.floor(b.min(0)).astype(int)
        x1, y1 = np.ceil(b.max(0)).astype(int)
        if t.strip():
            out.append(OcrLine([int(x0), int(y0), int(x1 - x0), int(y1 - y0)], t.strip(), float(s)))
    # same row = vertical centres within half the shorter box height
    out.sort(key=lambda l: (l.bbox[1] + l.bbox[3] / 2, l.bbox[0]))
    rows: list[list[OcrLine]] = []
    for l in out:
        c = l.bbox[1] + l.bbox[3] / 2
        if rows and abs(c - (rows[-1][0].bbox[1] + rows[-1][0].bbox[3] / 2)) < min(l.bbox[3], rows[-1][0].bbox[3]) / 2:
            rows[-1].append(l)
        else:
            rows.append([l])
    return [l for r in rows for l in sorted(r, key=lambda l: l.bbox[0])]
