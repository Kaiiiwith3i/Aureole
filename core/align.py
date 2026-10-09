"""Warp a photo/scan into page space. ArUco first, QR corners as fallback."""
from dataclasses import dataclass

import cv2
import numpy as np

from core import layout


@dataclass
class AlignResult:
    image: np.ndarray  # BGR, layout.size (W, H), border filled white
    H: np.ndarray  # 3x3 float64, input px -> page px
    method: str  # "aruco" | "qr"
    markers: int  # ArUco markers used (0 for the qr method)
    layout: layout.Layout


def _detector() -> cv2.aruco.ArucoDetector:
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.adaptiveThreshWinSizeMax = 63
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, layout.DICTIONARY)), p)


def _marker_points(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, int, layout.Layout | None]:
    """(src, dst, n markers, layout): detected corner px and their page px, for the layout (ids 0-3 portrait,
    4-7 landscape) with more detected markers (first hit per id)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    corners, ids, _ = _detector().detectMarkers(gray)
    found = {}
    for c, i in zip(corners, [] if ids is None else ids.ravel()):
        if 0 <= int(i) <= 7:
            found.setdefault(int(i), c.reshape(4, 2))
    ls = max((False, True), key=lambda ls: sum((i >= 4) == ls for i in found))
    mine = {i: c for i, c in found.items() if (i >= 4) == ls}
    if not mine:
        return np.empty((0, 2)), np.empty((0, 2)), 0, None
    L, m = layout.layout(ls), layout.MARKER
    src = np.concatenate(list(mine.values())).astype(np.float64)
    dst = np.array([[[x, y], [x + m, y], [x + m, y + m], [x, y + m]] for x, y in (L.markers[i] for i in mine)], np.float64)
    return src, dst.reshape(-1, 2), len(mine), L


def _sane(H: np.ndarray | None, shape: tuple, size: tuple[int, int]) -> bool:
    """Page quad mapped back into the input must be finite, convex and of plausible area."""
    if H is None or not np.all(np.isfinite(H)) or abs(np.linalg.det(H)) < 1e-12:
        return False
    w, h = size
    quad = cv2.perspectiveTransform(np.array([[[0, 0], [w, 0], [w, h], [0, h]]], np.float64), np.linalg.inv(H))[0]
    if not np.all(np.isfinite(quad)) or not cv2.isContourConvex(quad.astype(np.float32)):
        return False
    return 0.02 <= cv2.contourArea(quad.astype(np.float32)) / (shape[0] * shape[1]) <= 4.0


def align(image: np.ndarray, qr_corners: np.ndarray | None = None, qr_quad: np.ndarray | None = None,
          landscape: bool | None = None) -> AlignResult | None:
    """Detect DICT_4X4_50 markers (ids 0-3 portrait, 4-7 landscape; cv2.aruco.ArucoDetector). With >= 3 markers of one
    layout, fit a homography from all their corner points to that layout's marker positions (corner order TL, TR, BR, BL).
    Otherwise, if qr_corners, qr_quad (both (4,2), same order; qr_quad = qr.symbol_quad(seal, layout.qr)) and landscape
    are given, use those 4 points with layout.layout(landscape).
    Return None if neither works or the homography is degenerate (non-convex / absurd scale)."""
    src, dst, n, L = _marker_points(image)
    H, method = None, "aruco"
    if n >= 3:
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if not (n >= 3 and _sane(H, image.shape, L.size)):
        H = None
        if qr_corners is None or qr_quad is None or landscape is None:
            return None
        L, method, n = layout.layout(landscape), "qr", 0
        H = cv2.getPerspectiveTransform(np.asarray(qr_corners, np.float32).reshape(4, 2),
                                        np.asarray(qr_quad, np.float32).reshape(4, 2)).astype(np.float64)
        if not _sane(H, image.shape, L.size):
            return None
    warped = cv2.warpPerspective(image, H, L.size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    return AlignResult(warped, H.astype(np.float64), method, n, L)
