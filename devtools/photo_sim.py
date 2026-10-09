"""Phone-photo simulation for demo/test/training data. Deterministic per seed."""
import cv2
import numpy as np

DESK = (38, 46, 58)  # BGR, dark warm desk
MARGIN = 0.05  # canvas margin as a share of the page size; the 4% corner jitter always fits inside it


def simulate_photo(image: np.ndarray, seed: int = 0, strength: float = 1.0) -> np.ndarray:
    """BGR page -> BGR "photo": page perspective-warped onto a slightly larger dark desk background (whole page and all
    4 markers stay in frame), lighting gradient, mild warm tint, sensor noise, slight blur. Long side <= 3000 px.
    strength scales every effect (0 = identity apart from the canvas). The caller saves it as JPEG q75."""
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    mx, my = round(w * MARGIN), round(h * MARGIN)
    cw, ch = w + 2 * mx, h + 2 * my
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = rng.uniform(-0.04, 0.04, (4, 2)) * [w, h] * strength
    dst = (src + [mx, my] + jitter).astype(np.float32)
    M = cv2.getPerspectiveTransform(src, dst)

    gh, gw = ch // 8, cw // 8  # desk texture and lighting are smooth: build them small, then enlarge
    yy, xx = np.mgrid[0:gh, 0:gw].astype(np.float32)
    desk = (1 + 0.15 * np.sin(xx / 39 + rng.uniform(0, 6)) * np.sin(yy / 34 + rng.uniform(0, 6)))[..., None] * np.float32(DESK)
    ang = rng.uniform(0, 2 * np.pi)  # lighting: linear ramp 1.0 -> 0.75 along a random direction
    t = (xx - gw / 2) * np.cos(ang) + (yy - gh / 2) * np.sin(ang)
    t = (t - t.min()) / (t.max() - t.min())
    light = (1 - 0.25 * strength * t)[..., None] * np.array([1, 1, 1], np.float32)
    warm = 0.03 * strength * rng.uniform(0.3, 1.0)  # warm: less blue, more red (BGR)
    light *= np.array([1 - warm, 1.0, 1 + warm * 0.5], np.float32)
    desk, light = (cv2.resize(m, (cw, ch), interpolation=cv2.INTER_LINEAR) for m in (desk, light))

    page = cv2.warpPerspective(image, M, (cw, ch), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (cw, ch), flags=cv2.INTER_LINEAR)
    mask = (cv2.GaussianBlur(mask, (0, 0), 1.0).astype(np.float32) / 255)[..., None]
    out = (page * mask + desk * (1 - mask)) * light
    if strength > 0:
        out = cv2.GaussianBlur(out, (0, 0), rng.uniform(0.8, 1.0) * strength)
        out += rng.standard_normal(out.shape, dtype=np.float32) * (4.0 * strength)
    out = np.clip(out, 0, 255).astype(np.uint8)
    scale = 3000 / max(cw, ch)
    if scale < 1:
        out = cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return out


def save_jpeg(image: np.ndarray, path, quality: int = 75) -> None:
    if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, quality]):
        raise OSError(f"could not write {path}")
