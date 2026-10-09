"""Visual diff: expected render vs aligned scan -> change regions (both template size)."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Region:
    bbox: tuple[int, int, int, int]  # x, y, w, h in template px
    mask: np.ndarray  # uint8 (h, w), 255 where changed, cropped to bbox
    area: int  # changed pixels
    added: float  # 0..1 share of changed pixels that are ink present in the scan but not expected (rest = expected ink missing)


_K = np.ones((9, 9), np.uint8)  # +-4 px: absorbs 1-3 px residual misalignment
_MIN_PIXELS = 60  # changed pixels a region needs
_MAX_REGIONS = 40


def _norm(img: np.ndarray) -> np.ndarray:
    """float32 BGR divided per channel by the paper level: closing over ~340 px windows (bigger than any mark) -> lighting + tint gone."""
    small = cv2.resize(img, (img.shape[1] // 16, img.shape[0] // 16), interpolation=cv2.INTER_AREA)
    bg = cv2.GaussianBlur(cv2.dilate(small, np.ones((21, 21), np.uint8)), (0, 0), 1.5)
    bg = cv2.resize(bg, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    return img.astype(np.float32) / np.maximum(bg, 1.0)


def _ink_chroma(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = cv2.GaussianBlur(_norm(img), (0, 0), 1.2)
    b, g, r = cv2.split(n)  # cv2 min/max: numpy's axis-2 reduce is 5x slower here
    return 1.0 - cv2.cvtColor(n, cv2.COLOR_BGR2GRAY), cv2.max(cv2.max(b, g), r) - cv2.min(cv2.min(b, g), r)


def diff_regions(expected: np.ndarray, aligned: np.ndarray, ignore: list[list[int]] | None = None) -> list[Region]:
    """Both BGR, same size. Steps: grayscale -> illumination normalization (divide by a heavy blur) -> binarize both ->
    dilate each ink mask a few px to absorb misalignment -> added = scan ink not near expected ink, removed = expected ink
    not near scan ink -> also catch colored marks on what should be blank paper (saturation) -> morphology to merge nearby
    pieces -> connected components above a minimum area. `ignore` bboxes (markers, QR box) are zeroed out.
    A clean phone photo (perspective-corrected, JPEG q75, mild noise/blur, lighting gradient) should yield no or only tiny regions.
    Largest regions first; cap at 40."""
    h, w = expected.shape[:2]
    d_e, c_e = _ink_chroma(expected)
    d_a, c_a = _ink_chroma(aligned)
    ink_e = (d_e > 0.22).astype(np.uint8)
    # strict threshold for "scan has ink here", loose one for "scan still has ink near expected ink" (blur thins strokes)
    added = (d_a > 0.22) & (cv2.dilate(ink_e, _K) == 0)
    removed = (d_e > 0.22) & (cv2.dilate((d_a > 0.12).astype(np.uint8), _K) == 0)
    colored = (c_a - cv2.dilate(c_e, _K) > 0.09) & (cv2.dilate(ink_e, _K) == 0)
    # ponytail: colored marks over expected ink (stamp on text) are only seen where they also darken; add a chroma-vs-expected diff if that matters
    add = added | colored
    raw = (add | removed).astype(np.uint8)
    raw[:4], raw[-4:], raw[:, :4], raw[:, -4:] = 0, 0, 0, 0  # warp edge of the page
    for x, y, bw, bh in ignore or []:
        raw[max(y, 0):y + bh, max(x, 0):x + bw] = 0
    merged = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    # a fold line is cut wherever it crosses text (not "added" there): bridge long axis-aligned gaps
    # ponytail: diagonal folds only bridge via the 31 px close; add rotated kernels if they fragment
    for k in ((1, 221), (221, 1)):
        merged |= cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones(k[::-1], np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, bw, bh = (int(v) for v in stats[i, :4])
        m = ((lab[y:y + bh, x:x + bw] == i) & (raw[y:y + bh, x:x + bw] > 0))
        area = int(m.sum())
        if area < _MIN_PIXELS or max(bw, bh) < 12:
            continue
        a = int((m & add[y:y + bh, x:x + bw]).sum())
        out.append(Region((x, y, bw, bh), m.astype(np.uint8) * 255, area, a / area))
    out.sort(key=lambda r: -r.area)
    return out[:_MAX_REGIONS]


def diff_overlay(aligned: np.ndarray, regions: list[Region]) -> np.ndarray:
    """Copy of aligned with every region's changed pixels tinted red, for the UI's "Differences" layer."""
    out = aligned.copy()
    for r in regions:
        x, y, w, h = r.bbox
        view = out[y:y + h, x:x + w]
        m = r.mask > 0
        view[m] = (view[m] * 0.4 + np.array([0, 0, 255]) * 0.6).astype(np.uint8)
    return out
