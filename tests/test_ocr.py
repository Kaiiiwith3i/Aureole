import time

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR
from core.compare import normalize
from core.ocr import engine_name, read_lines, read_text, warm_up

CASES = [
    ("Maria Clara D. Santos", "DejaVuSerif-Bold.ttf", 84, (1836, 100)),
    ("2022-00123", "DejaVuSans.ttf", 50, (636, 100)),
    ("1.25", "DejaVuSans-Bold.ttf", 50, (436, 100)),
    ("BS Computer Science", "DejaVuSans.ttf", 50, (1316, 100)),
    ("With High Honors", "DejaVuSans.ttf", 50, (1316, 100)),
    ("2026-03-28", "DejaVuSans.ttf", 50, (436, 100)),
]


def render(text, font, size, wh):
    im = Image.new("RGB", wh, "white")
    ImageDraw.Draw(im).text((10, wh[1] // 2), text, fill=(17, 17, 17),
                            font=ImageFont.truetype(str(FONTS_DIR / font), size), anchor="lm")
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def degrade(bgr):
    b = cv2.GaussianBlur(bgr, (0, 0), 1.0).astype(np.float32)
    b += np.random.default_rng(0).normal(0, 4, b.shape)
    ok, buf = cv2.imencode(".jpg", np.clip(b, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 75])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    warm_up()


@pytest.mark.parametrize("text,font,size,wh", CASES)
def test_clean_print(text, font, size, wh):
    r = read_text(render(text, font, size, wh))
    assert normalize(r.text) == normalize(text) and r.confidence >= 0.9


@pytest.mark.parametrize("text,font,size,wh", CASES)
def test_degraded_print(text, font, size, wh):
    r = read_text(degrade(render(text, font, size, wh)))
    assert normalize(r.text) == normalize(text)


def test_blank():
    r = read_text(np.full((100, 636, 3), 255, np.uint8))
    assert (r.text, r.confidence) == ("", 0.0)


def test_engine_and_speed():
    assert engine_name()
    img = render("2022-00123", "DejaVuSans.ttf", 50, (636, 100))
    t = time.perf_counter()
    read_text(img)
    assert time.perf_counter() - t < 0.5


def test_read_lines_order_and_boxes():
    im = Image.new("RGB", (1200, 500), "white")
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), 50)
    d.text((600, 300), "Right side", fill=(17, 17, 17), font=f)
    d.text((40, 300), "Left side", fill=(17, 17, 17), font=f)
    d.text((40, 60), "Top line 2024", fill=(17, 17, 17), font=f)
    L = read_lines(cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR))
    assert [normalize(l.text) for l in L] == ["top line 2024", "left side", "right side"]
    for l, (x, y) in zip(L, [(40, 60), (40, 300), (600, 300)]):
        bx, by, bw, bh = l.bbox
        assert abs(bx - x) < 25 and by < y + 50 < by + bh + 20 and bw > 100 and l.confidence > 0.8


def test_read_lines_blank():
    assert read_lines(np.full((300, 600, 3), 255, np.uint8)) == []
