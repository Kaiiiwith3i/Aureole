"""The printed lines of an issued page, and the check of one line on a scan. Builder C."""
from dataclasses import dataclass

import cv2
import numpy as np
import pypdfium2 as pdfium

from core import compare, layout, ocr

ZONE_MARGIN = 8  # px around a line bbox when cropping for OCR
MAX_LINES = 150  # ponytail: lines OCR-checked per page (largest first); raise if dense spreadsheets need it


@dataclass
class LineCheck:
    status: str  # "MATCH" | "MISMATCH" | "UNREADABLE"
    read: str
    similarity: float
    confidence: float


_GAP = 3  # a gap wider than this many line heights starts a new line (table cells)


def _letters(text: str) -> str:
    """Normalized letters and digits only, so dropped punctuation or spacing never counts as a different value."""
    return "".join(c for c in compare.normalize(text) if c.isalnum())


def _crop(img: np.ndarray, bbox: list[int]) -> np.ndarray:
    x, y, w, h = bbox
    m = ZONE_MARGIN
    return img[max(0, y - m):max(0, y + h + m), max(0, x - m):max(0, x + w + m)]


def ink_only(crop: np.ndarray) -> np.ndarray:
    """The crop with coloured marks (stamp ink, ballpoint, stains) painted white: issued text is black."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    out = crop.copy()
    out[(hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 70)] = 255
    return out


def check_line(scan: np.ndarray, expected: np.ndarray, line: dict) -> LineCheck:
    """OCR the line's crop (+ZONE_MARGIN, ink_only) of `scan` and compare with line["text"] (compare.compare_field,
    numeric = line["numeric"]), then apply the near-match guard: a MATCH whose read is confident (>= compare.CONF_MIN),
    whose letters/digits differ from the issued text, while the same engine reads the same crop of `expected` exactly,
    is a MISMATCH. This is v1's pipeline._read_fields for one line (see git show HEAD:core/pipeline.py)."""
    signed, crop = line["text"], _crop(scan, line["bbox"])
    if crop.size == 0:
        return LineCheck("UNREADABLE", "", 0.0, 0.0)
    read = ocr.read_text(ink_only(crop))
    result = compare.compare_field(signed, read.text, read.confidence, line["numeric"])
    status = result.status
    # The 0.90 tolerance exists for OCR noise. A confident reading whose letters differ ("Santos" -> "Santoz") is not
    # noise if the same engine reads the clean render exactly: that is a reprint.
    if (status == "MATCH" and read.confidence >= compare.CONF_MIN and _letters(read.text) != _letters(signed)
            and _letters(ocr.read_text(_crop(expected, line["bbox"])).text) == _letters(signed)):
        status = "MISMATCH"
    return LineCheck(status, read.text, round(result.similarity, 3), round(read.confidence, 3))


def _text_layer_lines(pdf: bytes, index: int, size: tuple[int, int]) -> list[dict]:
    """Lines from pdfium's per-character boxes (px, top-left origin). Not get_rect/get_text_bounded: they bleed."""
    doc = pdfium.PdfDocument(pdf)
    try:
        page = doc[index]
        tp = page.get_textpage()
        n = tp.count_chars()
        text = tp.get_text_range(0, n) if n else ""
        H = size[1]
        # (char, x0, y0, x1, y1) px for every char with a real box; None for newlines/blank
        chars = []
        for i, c in enumerate(text[:n]):
            box = None
            if not c.isspace():
                l, b, r, t = tp.get_charbox(i)
                if r > l and t > b:
                    box = (l / layout.PT, H - t / layout.PT, r / layout.PT, H - b / layout.PT)
            chars.append((c, box))
    finally:
        doc.close()
    segs, cur = [], []
    for c, box in chars:  # split on newlines
        if c in "\r\n":
            segs.append(cur)
            cur = []
        else:
            cur.append((c, box))
    segs.append(cur)
    out = []
    for seg in segs:
        boxes = [b for _, b in seg if b]
        if not boxes:
            continue
        hmax = max(b[3] - b[1] for b in boxes)
        parts, part, prev_r = [], [], None
        for c, b in seg:
            if b and prev_r is not None and b[0] - prev_r > _GAP * hmax:
                parts.append(part)
                part = []
            part.append((c, b))
            if b:
                prev_r = b[2]
        parts.append(part)
        for part in parts:
            bs = [b for _, b in part if b]
            t = "".join(c for c, _ in part).strip()
            if bs and t:
                x0, y0 = min(b[0] for b in bs), min(b[1] for b in bs)
                x1, y1 = max(b[2] for b in bs), max(b[3] for b in bs)
                out.append((t, [int(x0) - 2, int(y0) - 2, int(x1 - x0) + 5, int(y1 - y0) + 5]))
    return out


def page_lines(pdf: bytes, index: int, image: np.ndarray) -> list[dict]:
    """Lines of issued page `index` (0-based); `image` is its clean render (stamp.render_page).
    Returns [{"bbox": [x, y, w, h], "text": str, "numeric": bool, "readable": bool}], top-to-bottom, in page px.
    - Source: the PDF text layer (per-character boxes grouped into lines; a line is split where the horizontal gap
      exceeds ~3x its height, so table cells become separate lines). If the page has no text inside the content box,
      ocr.read_lines(image) instead.
    - Only lines inside layout.content (the frame's own footer is not a line). Whitespace-only lines are dropped.
    - numeric = the text has no letters. readable = check_line(image, image, line).status == "MATCH"."""
    h, w = image.shape[:2]
    L = layout.layout(w > h)
    cx, cy, cw, ch = L.content
    inside = lambda b: b[0] >= cx - 4 and b[1] >= cy - 4 and b[0] + b[2] <= cx + cw + 4 and b[1] + b[3] <= cy + ch + 4
    found = [(t, b) for t, b in _text_layer_lines(pdf, index, L.size) if inside(b)]
    if not found:
        found = [(o.text, [o.bbox[0] - 2, o.bbox[1] - 2, o.bbox[2] + 4, o.bbox[3] + 4]) for o in ocr.read_lines(image)]
        found = [(t, b) for t, b in found if inside(b)]
    # top-to-bottom, then left-to-right; same row = centres within half a line
    found.sort(key=lambda f: (f[1][1] + f[1][3] / 2, f[1][0]))
    rows: list[list] = []
    for f in found:
        c, r = f[1][1] + f[1][3] / 2, rows[-1][0][1] if rows else None
        if r and abs(c - (r[1] + r[3] / 2)) < min(f[1][3], r[3]) / 2:
            rows[-1].append(f)
        else:
            rows.append([f])
    out = []
    for t, b in (f for r in rows for f in sorted(r, key=lambda f: f[1][0])):
        line = {"bbox": b, "text": t, "numeric": not any(c.isalpha() for c in t), "readable": False}
        line["readable"] = check_line(image, image, line).status == "MATCH"
        out.append(line)
    return out
