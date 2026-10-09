"""Warp a photo/scan into template space. ArUco first, QR corners as fallback."""
from dataclasses import dataclass

import numpy as np


@dataclass
class AlignResult:
    image: np.ndarray  # BGR, template size (1654, 2339, 3), border filled white
    H: np.ndarray  # 3x3 float64, input px -> template px
    method: str  # "aruco" | "qr"
    markers: int  # ArUco markers used (0 for the qr method)


def align(image: np.ndarray, qr_corners: np.ndarray | None = None, qr_template_quad: np.ndarray | None = None) -> AlignResult | None:
    """Detect DICT_4X4_50 markers 0-3 (cv2.aruco.ArucoDetector). With >= 3 of them, fit a homography from all their
    corner points to the template positions (templates/cert-v1.json markers; corner order TL, TR, BR, BL).
    Otherwise, if qr_corners and qr_template_quad (both (4,2), same order) are given, use those 4 points.
    Return None if neither works or the homography is degenerate (non-convex / absurd scale)."""
    raise NotImplementedError
