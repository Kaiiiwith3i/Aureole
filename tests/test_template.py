import cv2
import numpy as np
import pypdfium2 as pdfium

from core import qr, template

FIELDS = {"name": "Maria Santos", "student_id": "2021-00123", "program": "BS Computer Science",
          "award": "Cum Laude", "grade": "1.45", "date_issued": "2026-03-14"}
META = {"seal": None, "doc_id": "AB12CD34", "version": 1}


def _diff_bbox(a, b):
    ys, xs = np.nonzero((a != b).any(axis=2))
    return xs.min(), ys.min(), xs.max(), ys.max()


def _markers(img):
    dic = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    _, ids, _ = cv2.aruco.ArucoDetector(dic).detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    return set() if ids is None else set(ids.ravel().tolist())


def test_shape_and_determinism():
    a, b = template.render_certificate(FIELDS, META), template.render_certificate(FIELDS, META)
    assert a.shape == (1654, 2339, 3) and a.dtype == np.uint8
    assert a.tobytes() == b.tobytes()


def test_field_change_stays_in_bbox():
    a = template.render_certificate(FIELDS, META)
    b = template.render_certificate({**FIELDS, "award": "Magna Cum Laude"}, META)
    x, y, w, h = template.zones()["award"]["bbox"]
    x0, y0, x1, y1 = _diff_bbox(a, b)
    assert x0 >= x and y0 >= y and x1 < x + w and y1 < y + h


def test_markers_toggle():
    assert _markers(template.render_certificate(FIELDS, {**META, "markers": False})) == set()
    assert _markers(template.render_certificate(FIELDS, META)) == {0, 1, 2, 3}


def test_draw_field_outside_untouched():
    a = template.render_certificate(FIELDS, META)
    b = a.copy()
    template.draw_field(b, "grade", "3.99")
    x, y, w, h = template.zones()["grade"]["bbox"]
    mask = np.ones(a.shape[:2], bool)
    mask[y:y + h, x:x + w] = False
    assert (a[mask] == b[mask]).all()
    assert (a[~mask] != b[~mask]).any()


def test_png_and_pdf(tmp_path):
    img = template.render_certificate(FIELDS, META)
    template.save_png(img, tmp_path / "c.png")
    assert (cv2.imread(str(tmp_path / "c.png")) == img).all()
    template.save_pdf(img, tmp_path / "c.pdf")
    page = pdfium.PdfDocument(str(tmp_path / "c.pdf"))[0]
    out = page.render(scale=200 / 72).to_numpy()
    assert abs(out.shape[1] - 2339) <= 1 and abs(out.shape[0] - 1654) <= 1


def test_long_name_fits():
    img = template.render_certificate({**FIELDS, "name": "Maximiliana Bartholomew-Fitzgerald Montgomery"[:60].ljust(60, "W")}, META)
    x, y, w, h = template.zones()["name"]["bbox"]
    zone = img[y:y + h, x:x + w]
    assert (zone < 255).any()
    assert (zone[:, :4] == 255).all() and (zone[:, -4:] == 255).all()


def test_seal_uses_render_qr(monkeypatch):
    pat = (np.indices((540, 540)).sum(axis=0) % 2 * 255).astype(np.uint8)
    calls = []
    monkeypatch.setattr(qr, "render_qr", lambda text, size: calls.append((text, size)) or pat)
    img = template.render_certificate(FIELDS, {**META, "seal": "SG1.x.y"})
    assert calls == [("SG1.x.y", 540)]
    x, y, w, h = template.load_template()["qr"]["bbox"]
    assert (img[y:y + h, x:x + w, 0] == pat).all()
