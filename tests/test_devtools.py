import cv2
import numpy as np
import pytest

from core import seal, template
from devtools import tamper
from devtools.photo_sim import simulate_photo

FIELDS = {"name": "Test Person", "student_id": "2024-00001", "grade": "1.50", "program": "BS Testing",
          "award": "None", "date_issued": "2026-01-01"}


@pytest.fixture(scope="module")
def page():
    return template.render_certificate(FIELDS, {"seal": None, "doc_id": "t0000001", "version": 1})


def _calls(page):
    free = template.load_template()["free_areas"]
    return [lambda i: tamper.add_stamp(i, (900, 800), 100, seed=1), lambda i: tamper.add_scribble(i, free["scribble"], seed=1),
            lambda i: tamper.add_stain(i, (900, 800), 120, seed=1), lambda i: tamper.add_fold(i, 0.4, False, seed=1),
            lambda i: tamper.retype_field(i, "grade", "3.00"), lambda i: tamper.smudge_field(i, "name", seed=1),
            lambda i: tamper.copy_move(i, [100, 100, 300, 200], (900, 900))]


def test_tampers_pure_deterministic_and_in_page(page):
    before = page.copy()
    h, w = page.shape[:2]
    for call in _calls(page):
        out, (x, y, bw, bh) = call(page)
        assert np.array_equal(page, before) and not np.array_equal(out, page)
        assert 0 <= x and 0 <= y and bw > 0 and bh > 0 and x + bw <= w and y + bh <= h
        assert np.array_equal(out, call(page)[0])


def test_photo_sim(page):
    a = simulate_photo(page, seed=3)
    assert np.array_equal(a, simulate_photo(page, seed=3)) and not np.array_equal(a, simulate_photo(page, seed=4))
    assert 2400 <= max(a.shape[:2]) <= 3000
    ids = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)).detectMarkers(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY))[1]
    assert sorted(ids.ravel().tolist()) == [0, 1, 2, 3]


def test_retype_touches_only_its_zone(page):
    out, _ = tamper.retype_field(page, "grade", "3.00")
    x, y, w, h = template.zones()["grade"]["bbox"]
    changed = (out != page).any(2)
    assert changed.any() and not changed[:y].any() and not changed[y + h:].any()
    assert not changed[:, :x].any() and not changed[:, x + w:].any()


def test_rogue_seal_is_untrusted():
    from core import qr
    img = tamper.rogue_reseal(FIELDS, "rogue001")
    check = seal.verify_seal(qr.decode_qr(img).text, seal.load_trusted_keys())
    assert not check.ok and check.reason == "untrusted_kid"
