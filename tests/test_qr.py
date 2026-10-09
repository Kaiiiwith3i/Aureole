import cv2
import numpy as np
import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.qr import QUIET_MODULES, decode_qr, render_qr, symbol_quad
from core.seal import make_seal

_F = {"name": "Maria Cristina Santos-Villanueva", "student_id": "2021-00123", "program": "Bachelor of Science in Computer Science",
      "award": "Cum Laude", "grade": "1.45", "date_issued": "2026-03-15"}
TEXT = make_seal(_F, "ab12cd34", 1, Ed25519PrivateKey.generate())
assert 330 <= len(TEXT) <= 380, len(TEXT)


def page(bbox=(100, 80, 540, 540), size=(900, 800)):
    img = np.full((size[1], size[0]), 255, np.uint8)
    x, y, w, h = bbox
    img[y:y + h, x:x + w] = render_qr(TEXT, w)
    return img


def test_round_trip_and_quad():
    r = decode_qr(page())
    assert r.text == TEXT and r.corners.shape == (4, 2) and r.corners.dtype == np.float32
    assert np.abs(r.corners - symbol_quad(TEXT, [100, 80, 540, 540])).max() <= 3


def test_bgr_input():
    assert decode_qr(cv2.cvtColor(page(), cv2.COLOR_GRAY2BGR)).text == TEXT


def test_rot90():
    assert decode_qr(cv2.rotate(page(), cv2.ROTATE_90_CLOCKWISE)).text == TEXT


def test_rot7():
    img = page()
    m = cv2.getRotationMatrix2D((450, 400), 7, 1)
    assert decode_qr(cv2.warpAffine(img, m, (900, 800), borderValue=255)).text == TEXT


def test_blur():
    assert decode_qr(cv2.GaussianBlur(page(), (0, 0), 1.5)).text == TEXT


def test_downscale():
    assert decode_qr(cv2.resize(page(), None, fx=0.7, fy=0.7, interpolation=cv2.INTER_AREA)).text == TEXT


def test_blank_is_none():
    assert decode_qr(np.full((400, 400, 3), 255, np.uint8)) is None


def test_too_long():
    with pytest.raises(ValueError):
        render_qr("x" * 3000, 540)


def test_module_size_380_chars():
    import qrcode
    text = "SG1." + "A" * 376
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=1, border=0)
    qr.add_data(text)
    qr.make(fit=True)
    assert 540 // (qr.modules_count + 2 * QUIET_MODULES) >= 5
    assert render_qr(text, 540).shape == (540, 540)
