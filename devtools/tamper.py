"""Synthetic tampering and wear, applied to issued page images before photo simulation.
Every function returns (new_image, bbox [x, y, w, h] of what it touched) and never modifies its input. Deterministic per seed."""
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR


def _multiply(image: np.ndarray, alpha: np.ndarray, color_bgr) -> np.ndarray:
    """Ink-like blend: where alpha is 1 the page is multiplied by color/255, so text underneath still shows through."""
    col = np.array(color_bgr, np.float32) / 255
    f = 1 - alpha[..., None] * (1 - col)
    return np.clip(image.astype(np.float32) * f, 0, 255).astype(np.uint8)


def _bbox_of(alpha: np.ndarray, thr: float = 0.02) -> list[int]:
    ys, xs = np.nonzero(alpha > thr)
    if not len(xs):
        return [0, 0, 0, 0]
    return [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]


def add_stamp(image: np.ndarray, center: tuple[int, int], radius: int = 120, text: str = "RECEIVED", seed: int = 0):
    """Red circular rubber stamp (double ring + text), slightly rotated, semi-transparent."""
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    S = 4 * radius  # supersampled work canvas, rotation never clips
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    c, r = S / 2, radius
    d.ellipse([c - r, c - r, c + r, c + r], outline=255, width=max(3, r // 14))
    r2 = r * 0.82
    d.ellipse([c - r2, c - r2, c + r2, c + r2], outline=255, width=max(2, r // 28))
    font = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans-Bold.ttf"), max(12, int(r * 0.30)))
    while font.getbbox(text)[2] > 1.45 * r2 and font.size > 10:
        font = font.font_variant(size=font.size - 1)
    d.text((c, c), text, font=font, fill=255, anchor="mm")
    d.line([c - r2 * 0.72, c - font.size * 0.75, c + r2 * 0.72, c - font.size * 0.75], fill=255, width=max(2, r // 40))
    d.line([c - r2 * 0.72, c + font.size * 0.75, c + r2 * 0.72, c + font.size * 0.75], fill=255, width=max(2, r // 40))
    a = np.asarray(m, np.float32) / 255
    rot = cv2.getRotationMatrix2D((c, c), rng.uniform(-18, 18), 1.0)
    a = cv2.warpAffine(a, rot, (S, S), flags=cv2.INTER_LINEAR)
    # uneven ink: low-frequency blotches plus fine speckle dropout
    blot = cv2.GaussianBlur(rng.random((S // 8, S // 8)).astype(np.float32), (0, 0), 2)
    blot = cv2.resize((blot - blot.min()) / (np.ptp(blot) + 1e-6), (S, S))
    a *= 0.75 + 0.25 * blot
    a *= (rng.random((S, S)) > 0.06)
    a = cv2.GaussianBlur(a, (0, 0), 0.8)
    cx, cy = int(center[0]), int(center[1])
    x0, y0 = cx - S // 2, cy - S // 2
    layer = np.zeros((h, w), np.float32)
    sx0, sy0, sx1, sy1 = max(x0, 0), max(y0, 0), min(x0 + S, w), min(y0 + S, h)
    if sx1 > sx0 and sy1 > sy0:
        layer[sy0:sy1, sx0:sx1] = a[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
    return _multiply(image, layer, (45, 45, 205)), _bbox_of(layer)


def add_scribble(image: np.ndarray, bbox: list[int], seed: int = 0):
    """Blue ballpoint handwriting-like strokes inside bbox."""
    rng = np.random.default_rng(seed)
    x, y, bw, bh = bbox
    layer = np.zeros(image.shape[:2], np.uint8)
    cy, amp_max = y + bh / 2, bh / 2 - 5
    letters = max(4, bw // 55)
    step = (bw - 30) / letters
    px, py = [], []
    for i in range(letters):  # one looped "letter" per step: x drifts right while y oscillates
        amp = amp_max * (rng.uniform(0.75, 1.0) if rng.random() < 0.35 else rng.uniform(0.25, 0.5))  # tall and short letters
        t = np.linspace(0, 2 * np.pi, 14, endpoint=False)
        yy = cy - amp * np.cos(t) + 0.25 * amp * np.sin(2 * t) + rng.normal(0, 1.2, 14)
        px += list(x + 12 + (i + t / (2 * np.pi)) * step + 0.5 * step * np.sin(t) - 0.55 * (yy - cy) + rng.normal(0, 1.2, 14))  # forward slant
        py += list(yy)
    pts = np.array([px, py]).T
    pts[:, 0] = np.clip(pts[:, 0], x + 3, x + bw - 3)
    pts[:, 1] = np.clip(pts[:, 1], y + 3, y + bh - 3)
    tck = cv2.resize(pts.astype(np.float32).reshape(-1, 1, 2), (1, len(pts) * 6), interpolation=cv2.INTER_CUBIC).reshape(-1, 2)
    for p, q in zip(tck[:-1], tck[1:]):  # pressure varies along the stroke
        cv2.line(layer, tuple(int(v * 4) for v in p), tuple(int(v * 4) for v in q), int(rng.integers(190, 256)),
                 int(rng.choice([2, 3, 3, 4])), cv2.LINE_AA, shift=2)
    sy = y + bh - 8  # trailing underline
    cv2.line(layer, (x + 10, sy), (x + bw - 20, int(sy + rng.integers(-4, 5))), 200, 3, cv2.LINE_AA)
    a = cv2.GaussianBlur(layer.astype(np.float32) / 255, (0, 0), 0.7) * 0.9
    return _multiply(image, a, (170, 70, 25)), _bbox_of(a)


def add_stain(image: np.ndarray, center: tuple[int, int], radius: int = 150, seed: int = 0):
    """Brown coffee ring: darker irregular rim, pale translucent fill. Text underneath stays legible."""
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    th = np.linspace(0, 2 * np.pi, 180, endpoint=False)
    wob = sum(rng.uniform(0.01, 0.05) / k * np.sin(k * th + rng.uniform(0, 6.3)) for k in range(1, 6))
    rad = radius * (1 + wob)
    pts = np.stack([center[0] + rad * np.cos(th), center[1] + rad * np.sin(th)], 1)
    fill = np.zeros((h, w), np.uint8)
    cv2.fillPoly(fill, [np.round(pts * 4).astype(np.int32)], 255, cv2.LINE_AA, shift=2)
    rim = np.zeros((h, w), np.uint8)
    arc, phi = rng.uniform(0.75, 1.0), rng.uniform(0, 6.3)  # a ring rarely closes evenly: stronger on one side
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        s = 0.45 + 0.55 * (0.5 + 0.5 * np.cos(th[i] - phi)) ** (1 / arc)
        cv2.line(rim, tuple(np.round(pts[i] * 4).astype(int)), tuple(np.round(pts[j] * 4).astype(int)),
                 int(255 * s), max(2, int(radius * rng.uniform(0.035, 0.06))), cv2.LINE_AA, shift=2)
    rim = cv2.GaussianBlur(rim.astype(np.float32) / 255, (0, 0), max(1.0, radius / 60))
    soft = cv2.GaussianBlur(fill.astype(np.float32) / 255, (0, 0), max(1.5, radius / 40))
    mott = cv2.resize(cv2.GaussianBlur(rng.random((h // 16 + 1, w // 16 + 1)).astype(np.float32), (0, 0), 3), (w, h))
    mott = 0.75 + 0.5 * (mott - mott.min()) / (np.ptp(mott) + 1e-6)
    out = _multiply(image, soft * 0.16 * mott, (120, 170, 215))  # pale tan fill
    out = _multiply(out, np.clip(rim * 0.95, 0, 0.9), (60, 105, 160))  # darker brown rim
    return out, _bbox_of(np.maximum(soft, rim), 0.05)


def add_fold(image: np.ndarray, position: float = 0.5, vertical: bool = True, seed: int = 0):
    """Fold crease across the whole page at `position` (0..1): a thin dark line with a soft shading band."""
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    n, length = (w, h) if vertical else (h, w)
    c = position * n
    d = np.arange(n, dtype=np.float32) - c
    band = 45
    shade = np.where(d < 0, 0.06, -0.03) * np.exp(-(d / band) ** 2)  # darker on the valley side, lighter past the ridge
    line = 0.55 * np.exp(-(d / 1.6) ** 2)
    drift = np.cumsum(rng.normal(0, 0.15, length)).astype(np.float32)  # the line wanders slightly
    drift -= np.linspace(drift[0], drift[-1], length)
    idx = np.clip(np.arange(n)[None, :] - np.round(drift)[:, None], 0, n - 1).astype(int)
    f = 1 - (shade + line)[idx]
    f = f if vertical else f.T
    out = np.clip(image.astype(np.float32) * f[..., None], 0, 255).astype(np.uint8)
    lo = max(int(c) - band, 0)
    bbox = [lo, 0, min(int(c) + band, n) - lo, h] if vertical else [0, lo, w, min(int(c) + band, n) - lo]
    return out, bbox


def retype_line(image: np.ndarray, bbox: list[int], new_value: str):
    """Replace one printed line in an issued page image."""
    x, y, w, h = bbox
    out = Image.fromarray(image[:, :, ::-1].copy())
    draw = ImageDraw.Draw(out)
    draw.rectangle([x - 4, y - 4, x + w + 4, y + h + 4], fill="white")
    font = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), 26)
    draw.text((x, y + h), new_value, font=font, fill="black", anchor="ls")
    return np.asarray(out)[:, :, ::-1].copy(), [x, y, w, h]


def smudge_line(image: np.ndarray, bbox: list[int], seed: int = 0):
    """Heavy blur/smear over one printed line."""
    rng = np.random.default_rng(seed)
    out = image.copy()
    x, y, w, h = bbox
    crop = out[y:y + h, x:x + w].astype(np.float32)
    k = np.zeros((1, 81), np.float32)  # horizontal smear, then heavy blur and a vertical drag
    k[0] = 1 / 81
    crop = cv2.filter2D(crop, -1, k, borderType=cv2.BORDER_REPLICATE)
    crop = cv2.GaussianBlur(crop, (0, 0), 9, borderType=cv2.BORDER_REPLICATE)
    kv = np.full((31, 1), 1 / 31, np.float32)
    crop = cv2.filter2D(crop, -1, kv, borderType=cv2.BORDER_REPLICATE)
    crop = 255 - (255 - crop) * 1.6  # the smear keeps a grey ghost of the ink
    crop += rng.normal(0, 2, crop.shape)
    out[y:y + h, x:x + w] = np.clip(crop, 0, 255).astype(np.uint8)
    return out, [x, y, w, h]
