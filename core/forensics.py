"""Image forensics that need no seal: Error Level Analysis and copy-move detection."""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class CopyMoveHit:
    src: tuple[int, int, int, int]  # x, y, w, h (input px)
    dst: tuple[int, int, int, int]
    shift: tuple[int, int]  # dx, dy from src to dst
    blocks: int  # matched blocks sharing this shift
    confidence: float  # 0..1


_LONG = 2400  # copy_move shrinks bigger pages to this long side; finer than that the JPEG noise is small next to 2 px strokes
_PATCH, _PATCH_SMALL = 40, 10  # context patch around each keypoint (about a letter and its neighbours), compared at 10x10
_MIN_SIM = 0.93  # cosine similarity of two patches that count as the same content
_MIN_PAIRS = 8  # matched keypoint pairs sharing one shift, inside one compact cluster
_MIN_SHIFT = 40  # input px: closer than this is the same glyph/texture, not a copy
_MIN_H, _MIN_W = 85, 300  # input px: the cluster must be taller than one text line or wider than one word
_MAX_KP = 12000  # ponytail: SIFT keeps only the strongest keypoints, so a page denser than this can lose a copy's twin; raise _MAX_KP (cost grows with its square)


def ela(image: np.ndarray, quality: int = 90) -> np.ndarray:
    """Gray uint8 map, same HxW: |image - JPEG(image, quality)| max over channels, amplified to use the 0..255 range."""
    re = cv2.imdecode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])[1], cv2.IMREAD_COLOR)
    b, g, r = cv2.split(cv2.absdiff(image, re))
    d = cv2.max(cv2.max(b, g), r)
    # ponytail: scale is per-image (99.5th percentile -> 255), so maps are comparable within an image, not across images
    top = max(float(np.percentile(d[::4, ::4], 99.5)), 4.0)
    return cv2.convertScaleAbs(d, alpha=255.0 / top)


def heatmap(gray: np.ndarray) -> np.ndarray:
    """BGR colormap rendering of an ELA map for the UI."""
    return cv2.applyColorMap(gray, cv2.COLORMAP_JET)


def _bbox(pts: np.ndarray) -> tuple[int, int, int, int]:
    x0, y0 = np.maximum(pts.min(0) - 12, 0)  # keypoints sit at blob centres: pad to the glyph edges
    x1, y1 = pts.max(0) + 12
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def _same_pixels(g: np.ndarray, box: tuple[int, int, int, int], dx: int, dy: int) -> float:
    """Share of non-paper pixels in `box` that equal the pixels `dx, dy` away (best of +-1 px). Coincidentally repeated
    words match only where the words are; a real copy matches over the whole block."""
    x, y, w, h = box
    if x - dx < 2 or y - dy < 2 or x - dx + w > g.shape[1] - 2 or y - dy + h > g.shape[0] - 2 or x + w > g.shape[1] or y + h > g.shape[0]:
        return 0.0
    a = g[y:y + h, x:x + w]
    ink_a = np.abs(a - np.median(a)) > 40
    best = 0.0
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            b = g[y - dy + oy:y - dy + oy + h, x - dx + ox:x - dx + ox + w]
            ink = ink_a | (np.abs(b - np.median(b)) > 40)
            if ink.any():
                best = max(best, float((ink & (np.abs(a - b) < 60)).sum() / ink.sum()))
    return best


def copy_move(image: np.ndarray) -> list[CopyMoveHit]:
    """Block matching on overlapping blocks with robust (JPEG-tolerant) features. Flat/blank blocks are skipped.
    Only report a cluster of many blocks sharing the same shift vector (and a shift longer than the block size),
    so naturally repeated glyphs don't trigger it. Must run in < 1.5 s on a 2339x1654 page (downscale internally).
    Implementation: content-defined anchors (SIFT keypoint positions, parity-free unlike a block grid), a 40 px context
    patch at each (sub-pixel extracted, so one letter's twin differs from another 'e' by its neighbours), cosine matching,
    shift voting, then a pixel check of the whole candidate area. Hits are oriented so dst is the later one in reading
    order (lower, then righter); a hit alone cannot tell which copy is the original."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    f = min(1.0, _LONG / max(gray.shape))
    g = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else gray
    kp = cv2.SIFT_create(nfeatures=_MAX_KP).detect(g, None)
    gf = cv2.GaussianBlur(g.astype(np.float32), (0, 0), 1.2)
    pts = np.unique(np.round(np.array([k.pt for k in kp], np.float32) * 4) / 4, axis=0) if kp else np.zeros((0, 2), np.float32)
    pts = pts[(pts >= _PATCH / 2 + 1).all(1) & (pts[:, 0] < g.shape[1] - _PATCH / 2 - 1) & (pts[:, 1] < g.shape[0] - _PATCH / 2 - 1)]
    if len(pts) < 2 * _MIN_PAIRS:
        return []
    vec = np.stack([cv2.resize(cv2.getRectSubPix(gf, (_PATCH, _PATCH), (float(x), float(y))), (_PATCH_SMALL,) * 2, interpolation=cv2.INTER_AREA).ravel()
                    for x, y in pts])
    vec -= vec.mean(1, keepdims=True)
    nrm = np.linalg.norm(vec, axis=1)
    live = nrm > 40  # blank-ish patches say nothing
    pts, vec, nrm = pts[live], vec[live] / nrm[live, None], nrm[live]
    if len(pts) < 2 * _MIN_PAIRS:
        return []
    src, dst = [], []
    for i in range(0, len(vec), 2000):  # chunked cosine matrix: 12000^2 floats at once would be 576 MB
        sim = vec[i:i + 2000] @ vec.T
        sim[np.arange(sim.shape[0]), np.arange(i, i + sim.shape[0])] = -1  # not itself
        sim[np.linalg.norm(pts[i:i + 2000, None] - pts[None], axis=2) < _MIN_SHIFT * f] = -1  # nor its own neighbourhood
        for k in range(2):  # the two best partners: a word printed three times has two twins
            j = sim.argmax(1)
            ok = sim[np.arange(len(j)), j] > _MIN_SIM
            src += list(np.arange(i, i + len(j))[ok])
            dst += list(j[ok])
            sim[np.arange(len(j)), j] = -1
    if len(src) < _MIN_PAIRS:
        return []
    src, dst = np.array(src), np.array(dst)
    pts = pts / f
    shift = pts[dst] - pts[src]
    flip = (shift[:, 1] < -4) | ((np.abs(shift[:, 1]) <= 4) & (shift[:, 0] < 0))  # canonical: src -> dst goes down/right
    src, dst = np.where(flip, dst, src), np.where(flip, src, dst)
    shift = pts[dst] - pts[src]
    key = np.round(shift / 8.0).astype(np.int32)  # 8 px bins absorb keypoint jitter
    uk, cnt = np.unique(key, axis=0, return_counts=True)
    hits = []
    for k in np.argsort(-cnt)[:30]:
        if cnt[k] < _MIN_PAIRS:
            break
        near = np.abs(key - uk[k]).max(1) <= 1  # neighbouring bins are the same shift
        s_idx, d_idx = src[near], dst[near]
        cell = (pts[d_idx] // 32).astype(int)
        grid = np.zeros((int(cell[:, 1].max()) + 1, int(cell[:, 0].max()) + 1), np.uint8)
        grid[cell[:, 1], cell[:, 0]] = 1
        _, lab = cv2.connectedComponents(cv2.morphologyEx(grid, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)))
        lbl = lab[cell[:, 1], cell[:, 0]]
        keep = lbl == np.bincount(lbl[lbl > 0]).argmax() if (lbl > 0).any() else np.zeros(len(lbl), bool)
        if keep.sum() < _MIN_PAIRS:
            continue
        sb, db = _bbox(pts[s_idx[keep]]), _bbox(pts[d_idx[keep]])
        if db[3] < _MIN_H and db[2] < _MIN_W:  # about one repeated word
            continue
        sh = np.median(pts[d_idx[keep]] - pts[s_idx[keep]], 0)
        if _same_pixels(cv2.resize(gf, None, fx=1 / f, fy=1 / f) if f < 1 else gf, db, int(round(sh[0])), int(round(sh[1]))) < 0.75:
            continue
        hits.append(CopyMoveHit(sb, db, (int(round(sh[0])), int(round(sh[1]))), int(keep.sum()), float(min(1.0, keep.sum() / (_MIN_PAIRS * 3)))))
    return hits
