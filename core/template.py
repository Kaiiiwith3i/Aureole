"""Template spec + the one deterministic certificate renderer (used to issue AND to rebuild the expected page)."""
from pathlib import Path

import numpy as np


def load_template(name: str = "cert-v1") -> dict:
    """Parsed core.TEMPLATES_DIR/<name>.json, cached."""
    raise NotImplementedError


def zones(name: str = "cert-v1") -> dict[str, dict]:
    """{field key: field spec from the template} in template order."""
    raise NotImplementedError


def draw_field(image: np.ndarray, key: str, text: str) -> None:
    """In place: fill the field's bbox with white, then draw `text` with the field's font/size/align,
    vertically centered in the bbox, color template["value_color"]. Shared by render_certificate and devtools/tamper.py."""
    raise NotImplementedError


def render_certificate(fields: dict[str, str], meta: dict) -> np.ndarray:
    """BGR uint8 (1654, 2339, 3). Pure function of its arguments: same input -> byte-identical output.

    fields: long keys (name, student_id, program, award, grade, date_issued).
    meta: {"seal": str | None, "doc_id": str, "version": int, "markers": bool = True}
      - seal None  -> QR box left blank (and its caption skipped)
      - markers False -> no ArUco markers
      - doc_id falsy -> footer skipped
    Draws: white page, border, decor text/lines, field labels (label spec, at bbox x, bbox y + offset_y, left-top anchored),
    field values (draw_field), ArUco markers (cv2.aruco.generateImageMarker), QR (core.qr.render_qr into qr.bbox).
    Fonts only from core.FONTS_DIR via PIL.ImageFont.truetype.
    """
    raise NotImplementedError


def save_png(image: np.ndarray, path: Path) -> None:
    raise NotImplementedError


def save_pdf(image: np.ndarray, path: Path) -> None:
    """Single-page PDF at the template DPI (Pillow, resolution=200) so pypdfium2 at 200 DPI gives back 2339x1654."""
    raise NotImplementedError
