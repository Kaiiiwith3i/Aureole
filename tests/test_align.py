import cv2
import numpy as np
import pytest

from core import align, template

FIELDS = {"name": "Maria Santos", "student_id": "2021-00123", "program": "BS Computer Science",
          "award": "Cum Laude", "grade": "1.45", "date_issued": "2026-03-14"}
W, H = 2339, 1654
CORNERS = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
CANVAS = (2200, 3000)  # h, w


def _photo(page, seed, rot=0):
    """Page on a dark canvas under a random homography, then blur + noise + JPEG q75. Returns (img, true H input->template)."""
    rng = np.random.default_rng(seed)
    dst = (CORNERS + [330, 270] + rng.uniform(-0.04, 0.04, (4, 2)) * [W, H]).astype(np.float32)
    M = cv2.getPerspectiveTransform(CORNERS, dst)
    img = cv2.warpPerspective(page, M, CANVAS[::-1], borderValue=(40, 40, 40))
    img = cv2.GaussianBlur(img, (0, 0), 1.0).astype(np.float32) + rng.normal(0, 4, img.shape)
    img = cv2.imdecode(cv2.imencode(".jpg", np.clip(img, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 75])[1], 1)
    Hm = np.linalg.inv(M)
    if rot:
        img = cv2.rotate(img, rot)
        h, w = CANVAS
        R = {cv2.ROTATE_180: [[-1, 0, w - 1], [0, -1, h - 1], [0, 0, 1]],
             cv2.ROTATE_90_CLOCKWISE: [[0, -1, h - 1], [1, 0, 0], [0, 0, 1]]}[rot]
        Hm = Hm @ np.linalg.inv(np.array(R, float))
    return img, Hm


def _err(res, Htrue):
    inp = cv2.perspectiveTransform(CORNERS[None].astype(np.float64), np.linalg.inv(Htrue))
    return np.linalg.norm(cv2.perspectiveTransform(inp, res.H)[0] - CORNERS, axis=1).max()


@pytest.fixture(scope="module")
def page():
    return template.render_certificate(FIELDS, {"seal": None, "doc_id": "AB12CD34", "version": 1})


@pytest.mark.parametrize("rot", [0, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_aruco_alignment(page, seed, rot):
    img, Ht = _photo(page, seed, rot)
    res = align.align(img)
    assert res is not None and res.method == "aruco" and res.markers == 4
    assert res.image.shape == (H, W, 3)
    assert _err(res, Ht) < 3


def test_qr_fallback(seed=5):
    bare = template.render_certificate(FIELDS, {"seal": None, "doc_id": "AB12CD34", "version": 1, "markers": False})
    img, Ht = _photo(bare, seed)
    x, y, w, h = template.load_template()["qr"]["bbox"]
    quad = np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
    pts = cv2.perspectiveTransform(quad[None].astype(np.float64), np.linalg.inv(Ht))[0]
    res = align.align(img, pts, quad)
    assert res is not None and res.method == "qr" and res.markers == 0
    assert _err(res, Ht) < 5


def test_blank_is_none():
    assert align.align(np.full((1000, 1400, 3), 255, np.uint8)) is None


def test_two_markers_is_none(page):
    img = page.copy()
    for x, y in [(2199, 1514), (50, 1514)]:  # paint over ids 2 and 3
        img[y - 10:y + 100, x - 10:x + 100] = 255
    assert align.align(img) is None
