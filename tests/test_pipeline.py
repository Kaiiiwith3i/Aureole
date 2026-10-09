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


def test_marks_over_a_field_are_never_a_mismatch():
    """QA finding: a stamp or pen scribble on top of a value made OCR read junk with high confidence."""
    from core import template

    page = cv2.imread(str(pipeline.issue(FIELDS)["png_path"]))
    for key in ("student_id", "program", "name"):
        x, y, w, h = template.zones()[key]["bbox"]
        cx = x + w // 2 if key == "name" else x + 150
        for marked in (tamper.add_stamp(page, (cx, y + h // 2), 120, seed=1)[0],
                       tamper.add_scribble(page, [cx - 200, y - 8, 420, 100], seed=1)[0]):
            report = _verify(marked, photo_seed=11)
            assert report.verdict in ("AUTHENTIC_WITH_NOTES", "INCONCLUSIVE"), (key, report.headline)
            assert not any(f.severity == "critical" for f in report.findings)


def test_unprintable_or_unreadable_values_are_refused_at_issue():
    """QA finding: a name the font can't print was issued and then failed its own verification."""
    import pytest

    for name in ("王小明", "Иван Петров", "   "):
        with pytest.raises(ValueError):
            pipeline.issue({**FIELDS, "name": name})
    accented = pipeline.issue({**FIELDS, "name": "Zoë Ünal-Peñaflor"})
    assert pipeline.verify(accented["png_path"].read_bytes()).verdict == "AUTHENTIC"


def test_undecodable_uploads_raise_value_error():
    """QA finding: an empty file and a truncated PDF crashed the request."""
    import pytest

    pdf = pipeline.issue(FIELDS)["pdf_path"].read_bytes()
    for data in (b"", pdf[:3000], b"\x00" * 64, b"plain text"):
        with pytest.raises(ValueError):
            pipeline.verify(data)
