import functools

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR
from core.forensics import ela, heatmap

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
