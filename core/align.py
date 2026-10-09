"""Warp a photo/scan into template space. ArUco first, QR corners as fallback."""
from dataclasses import dataclass

import cv2
import numpy as np

from core.template import load_template


@dataclass
class AlignResult:
    image: np.ndarray  # BGR, template size (1654, 2339, 3), border filled white
    H: np.ndarray  # 3x3 float64, input px -> template px
    method: str  # "aruco" | "qr"
    markers: int  # ArUco markers used (0 for the qr method)


def _detector(t: dict) -> cv2.aruco.ArucoDetector:
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.adaptiveThreshWinSizeMax = 63
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, t["markers"]["dictionary"]))
    return cv2.aruco.ArucoDetector(dic, p)


def _marker_points(image: np.ndarray, t: dict) -> tuple[np.ndarray, np.ndarray, int]:
    """(src, dst, n markers): detected corner px and their template px, for ids 0-3 (first hit per id)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    corners, ids, _ = _detector(t).detectMarkers(gray)
    s = t["markers"]["size"]
    tpl = {it["id"]: it for it in t["markers"]["items"]}
    seen, src, dst = set(), [], []
    for c, i in zip(corners, [] if ids is None else ids.ravel()):
        i = int(i)
        if i not in tpl or i in seen:
            continue
        seen.add(i)
        x, y = tpl[i]["x"], tpl[i]["y"]
        src.append(c.reshape(4, 2))
        dst.append([[x, y], [x + s, y], [x + s, y + s], [x, y + s]])
    if not src:
        return np.empty((0, 2)), np.empty((0, 2)), 0
    return np.concatenate(src).astype(np.float64), np.array(dst, np.float64).reshape(-1, 2), len(seen)


def _sane(H: np.ndarray | None, shape: tuple, size: tuple[int, int]) -> bool:
    """Page quad mapped back into the input must be finite, convex and of plausible area."""
    if H is None or not np.all(np.isfinite(H)) or abs(np.linalg.det(H)) < 1e-12:
        return False
    w, h = size
    quad = cv2.perspectiveTransform(np.array([[[0, 0], [w, 0], [w, h], [0, h]]], np.float64), np.linalg.inv(H))[0]
    if not np.all(np.isfinite(quad)) or not cv2.isContourConvex(quad.astype(np.float32)):
        return False
    return 0.02 <= cv2.contourArea(quad.astype(np.float32)) / (shape[0] * shape[1]) <= 4.0


def align(image: np.ndarray, qr_corners: np.ndarray | None = None, qr_template_quad: np.ndarray | None = None) -> AlignResult | None:
    """Detect DICT_4X4_50 markers 0-3 (cv2.aruco.ArucoDetector). With >= 3 of them, fit a homography from all their
    corner points to the template positions (templates/cert-v1.json markers; corner order TL, TR, BR, BL).
    Otherwise, if qr_corners and qr_template_quad (both (4,2), same order) are given, use those 4 points.
    Return None if neither works or the homography is degenerate (non-convex / absurd scale)."""
    t = load_template()
    size = (t["page"]["width"], t["page"]["height"])
    src, dst, n = _marker_points(image, t)
    H, method = None, "aruco"
    if n >= 3:
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if not _sane(H, image.shape, size) and qr_corners is not None and qr_template_quad is not None:
        H = cv2.getPerspectiveTransform(np.asarray(qr_corners, np.float32).reshape(4, 2),
                                        np.asarray(qr_template_quad, np.float32).reshape(4, 2)).astype(np.float64)
        method, n = "qr", 0
    if not _sane(H, image.shape, size):
        return None
    warped = cv2.warpPerspective(image, H, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    return AlignResult(warped, H.astype(np.float64), method, n)
