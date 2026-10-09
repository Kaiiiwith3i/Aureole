"""The printed lines of an issued page, and the check of one line on a scan. Builder C."""
from dataclasses import dataclass

import numpy as np

ZONE_MARGIN = 8  # px around a line bbox when cropping for OCR
MAX_LINES = 150  # ponytail: lines OCR-checked per page (largest first); raise if dense spreadsheets need it


@dataclass
class LineCheck:
    status: str  # "MATCH" | "MISMATCH" | "UNREADABLE"
    read: str
    similarity: float
    confidence: float


def ink_only(crop: np.ndarray) -> np.ndarray:
    """The crop with coloured marks (stamp ink, ballpoint, stains) painted white: issued text is black."""
    raise NotImplementedError


def check_line(scan: np.ndarray, expected: np.ndarray, line: dict) -> LineCheck:
    """OCR the line's crop (+ZONE_MARGIN, ink_only) of `scan` and compare with line["text"] (compare.compare_field,
    numeric = line["numeric"]), then apply the near-match guard: a MATCH whose read is confident (>= compare.CONF_MIN),
    whose letters/digits differ from the issued text, while the same engine reads the same crop of `expected` exactly,
    is a MISMATCH. This is v1's pipeline._read_fields for one line (see git show HEAD:core/pipeline.py)."""
    raise NotImplementedError


def page_lines(pdf: bytes, index: int, image: np.ndarray) -> list[dict]:
    """Lines of issued page `index` (0-based); `image` is its clean render (stamp.render_page).
    Returns [{"bbox": [x, y, w, h], "text": str, "numeric": bool, "readable": bool}], top-to-bottom, in page px.
    - Source: the PDF text layer (per-character boxes grouped into lines; a line is split where the horizontal gap
      exceeds ~3x its height, so table cells become separate lines). If the page has no text inside the content box,
      ocr.read_lines(image) instead.
    - Only lines inside layout.content (the frame's own footer is not a line). Whitespace-only lines are dropped.
    - numeric = the text has no letters. readable = check_line(image, image, line).status == "MATCH"."""
    raise NotImplementedError
