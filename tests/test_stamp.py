import ctypes
import io

import cv2
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core import convert, layout, qr, seal, stamp

KEY = Ed25519PrivateKey.generate()
TRUSTED = {seal.kid_of(KEY.public_key()): KEY.public_key()}
TEXT3 = "\n".join(f"Line {i} of the Signet sample report, Peñaflor" for i in range(150))


def _landscape_pdf() -> bytes:
    d = pdfium.PdfDocument.new()
    pg = d.new_page(842, 595)
    font = raw.FPDFText_LoadStandardFont(d.raw, b"Helvetica")
    obj = raw.FPDFPageObj_CreateTextObj(d.raw, font, 24)
    w = "Landscape sample".encode("utf-16-le") + b"\0\0"
    raw.FPDFText_SetText(obj, ctypes.cast(ctypes.create_string_buffer(w, len(w)), ctypes.POINTER(ctypes.c_ushort)))
    raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 100, 300)
    raw.FPDFPage_InsertObject(pg.raw, obj)
    pg.gen_content()
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


@pytest.fixture(scope="module")
def three():
    content, _ = convert.to_pdf(TEXT3.encode(), "r.txt")
    return content, stamp.stamp(content, "ab12cd34", 3, KEY, "2026-10-10")


@pytest.fixture(scope="module")
def land():
    content = _landscape_pdf()
    return content, stamp.stamp(content, "ab12cd34", 1, KEY, "2026-10-10")


def _check(content, issued, landscape_flags, version):
    n = stamp.page_count(issued)
    assert n == stamp.page_count(content)
    dic = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    det = cv2.aruco.ArucoDetector(dic, cv2.aruco.DetectorParameters())
    for i in range(n):
        img = stamp.render_page(issued, i)
        L = layout.layout(landscape_flags[i])
        assert (img.shape[1], img.shape[0]) == L.size
        r = qr.decode_qr(img)
        chk = seal.verify_seal(r.text, TRUSTED)
        assert chk.ok
        d = chk.data
        assert (d.doc_id, d.version, d.page, d.pages, d.fingerprint) == ("ab12cd34", version, i + 1, n, stamp.fingerprint(content))
        corners, ids, _ = det.detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        got = {int(k): c.reshape(4, 2)[0] for k, c in zip(ids.ravel(), corners)}
        assert set(got) == set(L.markers)
        for k, (x, y) in L.markers.items():
            assert abs(got[k][0] - x) <= 3 and abs(got[k][1] - y) <= 3


def test_three_pages(three):
    content, issued = three
    assert stamp.page_count(content) == 3
    _check(content, issued, [False] * 3, 3)


def test_landscape(land):
    content, issued = land
    _check(content, issued, [True], 1)


def test_text_layer_survives(three, land):
    assert "Line 0 of the Signet sample report, Peñaflor" in pdfium.PdfDocument(three[1])[0].get_textpage().get_text_range()
    assert "Landscape sample" in pdfium.PdfDocument(land[1])[0].get_textpage().get_text_range()


def test_source_is_inside_content_box(three):
    img = stamp.render_page(three[1], 0)
    L = layout.layout(False)
    x, y, w, h = L.content
    dark = np.argwhere(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 128)
    inside = dark[(dark[:, 0] >= y - 2) & (dark[:, 0] < y + h + 2) & (dark[:, 1] >= x - 2) & (dark[:, 1] < x + w + 2)]
    assert len(inside) > 5000  # the text is there


def test_fingerprint():
    a, b = _landscape_pdf(), convert.to_pdf(b"x", "x.txt")[0]
    assert stamp.fingerprint(a) == stamp.fingerprint(a) and len(stamp.fingerprint(a)) == 16
    assert stamp.fingerprint(a) != stamp.fingerprint(b)
    assert stamp.fingerprint(convert.to_pdf(b"one", "a.txt")[0]) != stamp.fingerprint(convert.to_pdf(b"two", "a.txt")[0])


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
@pytest.mark.parametrize("origin", [(0, 0), (50, 60)])
def test_rotation_and_box_origin(rot, origin):
    d = pdfium.PdfDocument.new()
    pg = d.new_page(300, 200)
    ox, oy = origin
    pg.set_mediabox(ox, oy, ox + 300, oy + 200)
    rect = raw.FPDFPageObj_CreateNewRect(ox + 5, oy + 5, 40, 20)  # bottom-left corner of the unrotated page
    raw.FPDFPageObj_SetFillColor(rect, 255, 0, 0, 255)
    raw.FPDFPath_SetDrawMode(rect, 1, 0)
    raw.FPDFPage_InsertObject(pg.raw, rect)
    pg.gen_content()
    pg.set_rotation(rot)
    b = io.BytesIO()
    d.save(b)
    src = b.getvalue()
    shown = pdfium.PdfDocument(src)[0].render(scale=1).to_numpy()
    img = stamp.render_page(stamp.stamp(src, "ab12cd34", 1, KEY, "2026-10-10"), 0)
    L = layout.layout(shown.shape[1] > shown.shape[0])
    assert (img.shape[1], img.shape[0]) == L.size

    # relative position of the red box inside the page must match the source as displayed
    x, y, w, h = L.content
    crop = img[y:y + h, x:x + w]
    sh, sw = shown.shape[:2]
    s = min(w / sw, h / sh)
    exp = np.argwhere((shown[..., 2] > 200) & (shown[..., 0] < 60)).mean(0) / [sh, sw]
    p = np.argwhere((crop[..., 2] > 200) & (crop[..., 0] < 60) & (crop[..., 1] < 60)).mean(0)
    got = (p - [(h - sh * s) / 2, (w - sw * s) / 2]) / [sh * s, sw * s]
    assert np.abs(got - exp).max() < 0.02
