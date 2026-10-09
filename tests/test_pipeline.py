"""Pipeline regressions that the per-module tests can't see."""
import cv2

from core import pipeline
from devtools import tamper
from devtools.photo_sim import simulate_photo

FIELDS = {"name": "Maria Clara Santos", "student_id": "2024-10482", "program": "BS Computer Science",
          "award": "Dean's Lister", "grade": "1.45", "date_issued": "2026-03-14"}


def _verify(image, photo_seed=None):
    if photo_seed is not None:
        image = simulate_photo(image, seed=photo_seed)
    return pipeline.verify(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes(), "t.jpg")


def test_one_letter_edit_is_a_mismatch_but_a_genuine_photo_is_not():
    page = cv2.imread(str(pipeline.issue(FIELDS)["png_path"]))
    assert _verify(page, photo_seed=1).verdict == "AUTHENTIC"
    edited, _ = tamper.retype_field(page, "name", "Maria Clara Santoz")  # 0.94 similar: inside the OCR-noise tolerance
    for seed in (None, 2):
        report = _verify(edited, photo_seed=seed)
        assert report.verdict == "MISMATCH", report.headline
        assert any(f.severity == "critical" and f.field == "name" for f in report.findings)


def test_damage_over_a_field_is_never_a_mismatch():
    page = cv2.imread(str(pipeline.issue(FIELDS)["png_path"]))
    for key in ("name", "grade"):
        smudged, _ = tamper.smudge_field(page, key, seed=3)
        report = _verify(smudged, photo_seed=4)
        assert report.verdict == "INCONCLUSIVE", report.headline
        assert {f.key: f.status for f in report.fields}[key] == "UNREADABLE"


def test_unregistered_but_trusted_seal_is_verified_with_a_note(monkeypatch, tmp_path):
    png = pipeline.issue(FIELDS)["png_path"].read_bytes()
    monkeypatch.setenv("SIGNET_DATA_DIR", str(tmp_path / "another_machine"))  # registry that has never seen the document
    report = pipeline.verify(png, "t.png")
    assert report.verdict == "AUTHENTIC" and report.registry_status == "unknown" and report.notes
