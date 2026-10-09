import functools
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR
from core.forensics import copy_move, ela, heatmap

W, H = 2339, 1654


@functools.lru_cache(maxsize=1)
def text_doc() -> np.ndarray:
    """White page, 14 lines of seeded random words (so words repeat) in the left 1500 px."""
    rng = np.random.default_rng(7)
    letters = list("abcdefghijklmnoprstuvy")
    words = ["".join(rng.choice(letters, rng.integers(3, 10))) for _ in range(45)]  # 45-word vocabulary: words repeat, phrases don't
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(str(FONTS_DIR / "DejaVuSerif.ttf"), 38)
    seen, prev = set(), ""
    for row in range(14):
        line = []
        while len(line) < 7:
            w = str(rng.choice(words))
            if (prev, w) not in seen:  # single words repeat; word pairs never do (a repeated phrase IS a copy)
                seen.add((prev, w))
                line.append(w)
                prev = w
        d.text((150, 120 + row * 52), " ".join(line), font=font, fill=(20, 20, 20))
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def jpeg(img, q):
    return cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], 1)


def iou(a, b):
    iw = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    ih = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(iw, 0) * max(ih, 0) / (a[2] * a[3] + b[2] * b[3] - max(iw, 0) * max(ih, 0))


def test_ela_shape_and_pasted_region_is_brighter():
    base = text_doc()
    first = jpeg(base, 75)  # an earlier save: everything already sits on the JPEG grid
    pasted = first.copy()
    pasted[600:800, 700:1100] = text_doc()[600:800, 700:1100]  # fresh, never-compressed pixels
    e = ela(pasted, 90)
    assert e.shape == (H, W) and e.dtype == np.uint8 and e.ndim == 2
    assert e[600:800, 700:1100].mean() > 1.5 * e[1000:1600, 1600:2200].mean() + 1
    h = heatmap(e)
    assert h.shape == (H, W, 3) and h.dtype == np.uint8


def test_copy_move_finds_copied_block():
    for name, (sx, sy, dx, dy) in {"to blank": (150, 172, 1700, 500), "over text": (150, 172, 600, 700), "mid-line": (160, 224, 900, 1000)}.items():
        doc = text_doc().copy()
        doc[dy:dy + 90, dx:dx + 220] = doc[sy:sy + 90, sx:sx + 220]
        t = time.perf_counter()
        hits = copy_move(jpeg(doc, 85))
        assert hits, name
        assert any(iou(h.dst, (dx, dy, 220, 90)) > 0.5 for h in hits), (name, hits)
        assert any(iou(h.src, (sx, sy, 220, 90)) > 0.5 for h in hits), (name, hits)
        assert time.perf_counter() - t < 1.5
        assert len(hits) == 1, (name, hits)


def test_copy_move_quiet_on_clean_documents():
    assert copy_move(text_doc()) == []
    assert copy_move(jpeg(text_doc(), 85)) == []
    assert copy_move(jpeg(text_doc(), 75)) == []
    assert copy_move(np.full((H, W, 3), 255, np.uint8)) == []
