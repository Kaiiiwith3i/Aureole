import io

import cv2
import numpy as np
import pypdfium2 as pdfium
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core import align, convert, layout, qr, stamp
from devtools.photo_sim import simulate_photo

KEY = Ed25519PrivateKey.generate()


def _landscape_content() -> bytes:
    d = pdfium.PdfDocument.new()
    d.new_page(842, 595)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


@pytest.fixture(scope="module")
def portrait():
    content, _ = convert.to_pdf(("Sample paragraph for alignment tests. " * 40).encode(), "a.txt")
    return stamp.render_page(stamp.stamp(content, "ab12cd34", 1, KEY, "2026-10-10"), 0)


@pytest.fixture(scope="module")
def landscape():
    return stamp.render_page(stamp.stamp(_landscape_content(), "ab12cd34", 1, KEY, "2026-10-10"), 0)


def _warp(page, rot=None):
    """Perspective-warp a page onto a bigger dark canvas; returns (img, M page->img)."""
    h, w = page.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = (src * 0.8 + [200, 150] + np.float32([[30, 10], [-40, 25], [20, -35], [-10, 30]])).astype(np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    cw, ch = int(w * 0.8 + 450), int(h * 0.8 + 350)
    img = cv2.warpPerspective(page, M, (cw, ch), borderValue=(40, 40, 40))
    if rot is not None:
        img = cv2.rotate(img, rot)
    return img


def _mad(a, b):
    """Mean abs difference after a light blur, so sub-pixel resampling of fine text doesn't count."""
    a, b = (cv2.GaussianBlur(x, (0, 0), 3).astype(np.int16) for x in (a, b))
    return np.abs(a - b).mean()


def _marker_err(res):
    """Max distance (px) between the markers detected in the aligned image and their layout positions."""
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(cv2.cvtColor(res.image, cv2.COLOR_BGR2GRAY))
    assert ids is not None and set(ids.ravel()) == set(res.layout.markers)
    return max(np.abs(c.reshape(4, 2)[0] - res.layout.markers[int(i)]).max() for c, i in zip(corners, ids.ravel()))


def test_identity(portrait):
    res = align.align(portrait)
    assert res.method == "aruco" and res.markers == 4 and res.layout == layout.layout(False)
    assert res.image.shape == (2339, 1654, 3)
    assert np.abs(res.H - np.eye(3)).max() < 0.01 or np.abs(cv2.perspectiveTransform(np.float64([[[500, 900]]]), res.H)[0, 0] - [500, 900]).max() < 1
    assert _mad(res.image, portrait) < 2 and _marker_err(res) <= 1.5


@pytest.mark.parametrize("rot", [None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180])
def test_warped_and_rotated(portrait, rot):
    res = align.align(_warp(portrait, rot))
    assert res is not None and res.method == "aruco" and res.markers == 4
    assert res.image.shape == portrait.shape
    assert _mad(res.image, portrait) < 6 and _marker_err(res) <= 3


def test_landscape_from_marker_ids(landscape):
    res = align.align(_warp(landscape))
    assert res.layout.landscape and res.image.shape == (1654, 2339, 3)
    assert _mad(res.image, landscape) < 6 and _marker_err(res) <= 3


def test_photo_sim(portrait):
    res = align.align(simulate_photo(portrait, seed=3, strength=1.0))
    assert res is not None and res.markers >= 3
    assert _marker_err(res) <= 4  # lighting gradient, noise and blur make pixel comparison meaningless


def test_qr_fallback_when_markers_missing(portrait):
    img = _warp(portrait)
    L = layout.layout(False)
    # paint out 2 markers: only 2 remain, so alignment must use the QR corners
    M_pts = {}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(gray)
    for c, i in zip(corners, ids.ravel()):
        if int(i) in (0, 3):
            cv2.fillConvexPoly(img, cv2.convexHull(c.reshape(4, 2)).astype(np.int32), (255, 255, 255))
            M_pts[int(i)] = 1
    assert len(M_pts) == 2
    assert align.align(img) is None  # no QR info: cannot align
    r = qr.decode_qr(img)
    res = align.align(img, r.corners, qr.symbol_quad(r.text, L.qr), False)
    assert res.method == "qr" and res.markers == 0 and res.layout == L
    # four QR corners extrapolate over the whole page, so only the area around the QR is expected to be tight
    x, y, w, h = L.footer[0], L.qr[1] - 30, L.size[0] - L.footer[0], L.qr[3] + 60
    assert _mad(res.image[y:y + h, x:x + w], portrait[y:y + h, x:x + w]) < 8
    assert _mad(res.image, portrait) < 30


def test_blank_is_none():
    assert align.align(np.full((800, 600, 3), 255, np.uint8)) is None
    assert align.align(np.full((800, 600, 3), 255, np.uint8), np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]),
                       np.float32([[0, 0], [9, 0], [9, 9], [0, 9]]), None) is None
