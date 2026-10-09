import functools

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR
from core.diff import diff_overlay, diff_regions

W, H = 2339, 1654
MARKERS = [[50, 50, 90, 90], [2199, 50, 90, 90], [2199, 1514, 90, 90], [50, 1514, 90, 90]]
ZONE = [180, 1100, 1300, 84]  # an "award"-like zone
LINES = [  # (xy, size, text, font)
    ((270, 440), 84, "Juan Dela Cruz Santos", "DejaVuSerif-Bold.ttf"),
    ((180, 740), 50, "2021-00417", "DejaVuSans.ttf"),
    ((900, 740), 50, "1.45", "DejaVuSans-Bold.ttf"),
    ((180, 920), 50, "BS Computer Science", "DejaVuSans.ttf"),
    ((180, 1100), 50, "Dean's List with Honors", "DejaVuSans.ttf"),
    ((180, 1280), 50, "2026-03-14", "DejaVuSans.ttf"),
    ((1169 - 330, 1560), 24, "Document ab12cd34 - version 1 - DEMO, not a real credential", "DejaVuSans.ttf"),
]


@functools.lru_cache(maxsize=4)
def page(retype: str | None = None) -> np.ndarray:
    """Clean 'expected' page; `retype` whites out the ZONE line and prints different text instead."""
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([24, 24, W - 24, H - 24], outline=(74, 42, 27), width=4)
    d.text((1169, 300), "Certificate of Achievement", font=ImageFont.truetype(str(FONTS_DIR / "DejaVuSerif-Bold.ttf"), 92), fill=(74, 42, 27), anchor="mm")
    for xy, size, text, font in LINES:
        if retype is not None and xy == (180, 1100):
            text = retype
        d.text(xy, text, font=ImageFont.truetype(str(FONTS_DIR / font), size), fill=(17, 17, 17))
    for x, y, w, h in MARKERS:
        d.rectangle([x, y, x + w, y + h], fill=(0, 0, 0))
    out = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    out.flags.writeable = False  # shared by the cache
    return out


def photo(img: np.ndarray, seed: int = 1) -> np.ndarray:
    """Phone-photo degradation: shift, blur, lighting gradient, warm tint, noise, JPEG q75."""
    rng = np.random.default_rng(seed)
    out = cv2.warpAffine(img, np.float32([[1, 0, 1.5], [0, 1, -1.2]]), (W, H), borderValue=(255, 255, 255))
    out = cv2.GaussianBlur(out, (0, 0), 1.0).astype(np.float32)
    gx = np.linspace(1.0, 0.75, W)[None, :] * np.linspace(1.0, 0.9, H)[:, None]
    out *= gx[..., None] * np.array([0.97, 0.99, 1.0], np.float32)  # BGR: warm = less blue
    out += rng.normal(0, 4, out.shape)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return cv2.imdecode(cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 75])[1], 1)


def blend(img, draw_fn, color, alpha):
    layer = np.zeros(img.shape[:2], np.uint8)
    draw_fn(layer)
    a = (cv2.GaussianBlur(layer, (0, 0), 0.8).astype(np.float32) / 255 * alpha)[..., None]
    return (img * (1 - a) + np.array(color, np.float32) * a).astype(np.uint8)


def mark(kind: str) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    """(expected, scene-with-mark, ground-truth bbox)."""
    exp = page()
    img = exp.copy()
    if kind == "stamp":
        def f(m):
            cv2.circle(m, (1820, 760), 118, 255, 9)
            cv2.circle(m, (1820, 760), 92, 255, 3)
            cv2.rectangle(m, (1730, 745), (1910, 778), 255, 3)
        return exp, blend(img, f, (40, 40, 200), 0.6), (1702, 642, 236, 236)
    if kind == "scribble":
        rng = np.random.default_rng(3)
        pts = np.stack([np.linspace(900, 1380, 40), 1275 + rng.uniform(-45, 45, 40)], 1).astype(np.int32)
        return exp, blend(img, lambda m: cv2.polylines(m, [pts], False, 255, 3), (150, 60, 20), 0.9), (900, 1225, 480, 100)
    if kind == "stain":
        def f(m):
            cv2.ellipse(m, (1000, 960), (150, 140), 0, 0, 360, 255, 7)
        img = blend(img, lambda m: cv2.ellipse(m, (1000, 960), (146, 136), 0, 0, 360, 255, -1), (120, 170, 205), 0.25)
        return exp, blend(img, f, (35, 80, 125), 0.8), (850, 820, 300, 280)
    if kind == "fold":
        img = img.astype(np.float32)
        band = np.zeros((H, W), np.float32)
        cv2.line(band, (1300, 0), (1316, H), 1.0, 40)
        img *= (1 - 0.08 * cv2.GaussianBlur(band, (0, 0), 10))[..., None]
        img = img.astype(np.uint8)
        cv2.line(img, (1300, 0), (1316, H), (70, 70, 70), 2)
        return exp, img, (1300, 0, 16, H)
    if kind == "text":
        return exp, page(retype="Cum Laude, Dept of Math"), tuple(ZONE)
    raise ValueError(kind)


def overlaps(bbox, gt, frac=0.3):
    ax, ay, aw, ah = bbox
    bx, by, bw, bh = gt
    iw = min(ax + aw, bx + bw) - max(ax, bx)
    ih = min(ay + ah, by + bh) - max(ay, by)
    return iw > 0 and ih > 0 and iw * ih >= frac * min(aw * ah, bw * bh)


def test_clean_photo_has_no_regions():
    exp = page()
    for seed in (1, 2):
        regs = diff_regions(exp, photo(exp, seed), MARKERS)
        assert [r for r in regs if r.area > 150] == [], [(r.bbox, r.area) for r in regs]
        assert len(regs) <= 2


def test_marks_are_found():
    for kind in ("stamp", "scribble", "stain", "fold", "text"):
        exp, scene, gt = mark(kind)
        regs = diff_regions(exp, photo(scene), MARKERS)
        hits = [r for r in regs if overlaps(r.bbox, gt)]
        assert hits, (kind, [(r.bbox, r.area) for r in regs])
        assert len(regs) <= 3, (kind, [(r.bbox, r.area) for r in regs])
        if kind == "fold":
            assert max(r.bbox[3] for r in hits) > 0.9 * H
        if kind == "text":
            assert max(r.added for r in hits) < 0.8 and min(r.added for r in hits) > 0.0
            assert hits[0].added < 0.8


def test_ignore_suppresses_regions():
    exp, scene, gt = mark("stamp")
    assert diff_regions(exp, photo(scene), [[gt[0] - 20, gt[1] - 20, gt[2] + 40, gt[3] + 40]]) == []


def test_overlay_changes_only_inside_bboxes():
    exp, scene, _ = mark("stamp")
    al = photo(scene)
    regs = diff_regions(exp, al)
    out = diff_overlay(al, regs)
    assert out.shape == al.shape and out.dtype == al.dtype
    diff = (out != al).any(2)
    assert diff.any()
    keep = np.zeros_like(diff)
    for r in regs:
        x, y, w, h = r.bbox
        keep[y:y + h, x:x + w] = True
    assert not diff[~keep].any()
    assert regs[0].mask.shape == (regs[0].bbox[3], regs[0].bbox[2])
