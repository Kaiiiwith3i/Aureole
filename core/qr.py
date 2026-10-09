"""QR render (qrcode, level H) and robust decode (zxing-cpp, fallback cv2.QRCodeDetector)."""
from dataclasses import dataclass

import numpy as np

QUIET_MODULES = 2  # the page around the QR box is white, so 2 modules inside the box is enough
MAX_VERSION = 20


@dataclass
class QRResult:
    text: str
    corners: np.ndarray  # (4, 2) float32, symbol corners WITHOUT quiet zone, order TL, TR, BR, BL in the symbol's own orientation, input-image px


def render_qr(text: str, size_px: int) -> np.ndarray:
    """Gray uint8 (size_px, size_px) image, white background, symbol centered.

    Lowest version that fits at level H; if that exceeds MAX_VERSION use level Q and log a warning;
    if it still exceeds MAX_VERSION raise ValueError. Module size = size_px // (modules + 2*QUIET_MODULES), integer px.
    """
    raise NotImplementedError


def symbol_quad(text: str, bbox: list[int]) -> np.ndarray:
    """(4, 2) float32 corners TL, TR, BR, BL (outer edge of the symbol, no quiet zone) in template px
    when render_qr(text, bbox[2]) is pasted at bbox [x, y, w, h]. Used for the QR-corner alignment fallback."""
    raise NotImplementedError


def decode_qr(image: np.ndarray) -> QRResult | None:
    """Find a QR code in a BGR or gray image. Try zxing-cpp, then cv2.QRCodeDetector on: original, grayscale,
    2x upscale, adaptive threshold. If several codes are found prefer one whose text starts with "SG1.". None if nothing decodes."""
    raise NotImplementedError
