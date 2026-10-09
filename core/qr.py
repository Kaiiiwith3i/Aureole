"""QR render (qrcode, level H) and robust decode (zxing-cpp, fallback cv2.QRCodeDetector)."""
from dataclasses import dataclass

import cv2
import numpy as np
import qrcode
import zxingcpp
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_Q

from core import log

QUIET_MODULES = 2  # the page around the QR box is white, so 2 modules inside the box is enough
MAX_VERSION = 20


@dataclass
class QRResult:
    text: str
    corners: np.ndarray  # (4, 2) float32, symbol corners WITHOUT quiet zone, order TL, TR, BR, BL in the symbol's own orientation, input-image px


def _build(text: str) -> qrcode.QRCode:
    for level, name in ((ERROR_CORRECT_H, "H"), (ERROR_CORRECT_Q, "Q")):
        qr = qrcode.QRCode(version=None, error_correction=level, box_size=1, border=0)
        qr.add_data(text)
        qr.make(fit=True)
        if qr.version <= MAX_VERSION:
            if name != "H":
                log.warning("QR text too long for level H, using level Q (version %s)", qr.version)
            return qr
    raise ValueError(f"text too long for a QR code up to version {MAX_VERSION}")


def _geometry(n: int, size_px: int) -> tuple[int, int]:
    """(module px, symbol offset px inside the box)."""
    module = size_px // (n + 2 * QUIET_MODULES)
    if module < 1:
        raise ValueError("size_px too small for this QR code")
    return module, (size_px - module * n) // 2


def render_qr(text: str, size_px: int) -> np.ndarray:
    """Gray uint8 (size_px, size_px) image, white background, symbol centered.

    Lowest version that fits at level H; if that exceeds MAX_VERSION use level Q and log a warning;
    if it still exceeds MAX_VERSION raise ValueError. Module size = size_px // (modules + 2*QUIET_MODULES), integer px.
    """
    qr = _build(text)
    n = qr.modules_count
    module, off = _geometry(n, size_px)
    dark = np.kron(np.array(qr.get_matrix(), dtype=np.uint8), np.ones((module, module), np.uint8))
    img = np.full((size_px, size_px), 255, np.uint8)
    img[off:off + n * module, off:off + n * module] = np.where(dark == 1, 0, 255)
    return img


def symbol_quad(text: str, bbox: list[int]) -> np.ndarray:
    """(4, 2) float32 corners TL, TR, BR, BL (outer edge of the symbol, no quiet zone) in template px
    when render_qr(text, bbox[2]) is pasted at bbox [x, y, w, h]. Used for the QR-corner alignment fallback."""
    x, y, w, _ = bbox
    n = _build(text).modules_count
    module, off = _geometry(n, w)
    x0, y0, s = x + off, y + off, module * n
    return np.array([[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s]], np.float32)


def _zxing(img: np.ndarray):
    for r in zxingcpp.read_barcodes(img):
        p = r.position
        yield r.text, np.array([[q.x, q.y] for q in (p.top_left, p.top_right, p.bottom_right, p.bottom_left)], np.float32)


def _cv2(img: np.ndarray):
    try:
        text, pts, _ = cv2.QRCodeDetector().detectAndDecode(img)
    except cv2.error:
        return
    if text and pts is not None:
        yield text, np.asarray(pts, np.float32).reshape(4, 2)  # ponytail: assumes cv2 returns TL,TR,BR,BL (its documented order)


def decode_qr(image: np.ndarray) -> QRResult | None:
    """Find a QR code in a BGR or gray image. Try zxing-cpp, then cv2.QRCodeDetector on: original, grayscale,
    2x upscale, adaptive threshold. If several codes are found prefer one whose text starts with "SG1.". None if nothing decodes."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 10)
    variants = [(image, 1), (gray, 1), (big, 2), (thr, 1)]
    for detect in (_zxing, _cv2):
        found = []
        for img, scale in variants:
            found = [QRResult(t, c / scale) for t, c in detect(img)]
            if found:
                break
        if found:
            return next((r for r in found if r.text.startswith("SG1.")), found[0])
    return None
