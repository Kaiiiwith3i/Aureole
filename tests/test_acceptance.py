"""Acceptance: build the demo set into a temp data dir and check every verdict. Run with -s to see the table."""
import json
import os

import pytest

FILES = [
    "01_genuine.png", "02_genuine_photo.jpg", "03_stained_folded.jpg", "04_stamped_annotated.jpg", "05_grade_edited.png",
    "06_name_edited_photo.jpg", "07_revoked.png", "08_untrusted_seal.png", "09_smudged_field.jpg", "10_no_seal_edited.jpg",
]
XFAIL: dict[str, str] = {}  # file -> reason; see DECISIONS.md. Empty means every case must pass.
MAX_MS = 5000


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    from core import ocr
    from devtools.demo_set import build_demo_set

    root = tmp_path_factory.mktemp("acceptance")
    old = os.environ.get("SIGNET_DATA_DIR")
    os.environ["SIGNET_DATA_DIR"] = str(root / "data")
    try:
        expected = build_demo_set(root / "demo")
    finally:
        os.environ.pop("SIGNET_DATA_DIR") if old is None else os.environ.__setitem__("SIGNET_DATA_DIR", old)
    assert json.loads((root / "demo" / "expected.json").read_text()) == expected
    ocr.warm_up()
    rows = []
    yield root, expected, rows
    print("\n\nfile                         expected               actual                 ms")
    for name, want, got, ms in sorted(rows):
        print(f"{name:28} {want:22} {got:22} {ms:6.0f}")


@pytest.mark.parametrize("name", [pytest.param(f, marks=pytest.mark.xfail(reason=XFAIL[f], strict=True)) if f in XFAIL else f for f in FILES])
def test_demo_file(name, demo, monkeypatch):
    from core import pipeline

    root, expected, rows = demo
    monkeypatch.setenv("SIGNET_DATA_DIR", str(root / "data"))  # the registry the demo set was issued into
    want = expected[name]
    report = pipeline.verify((root / "demo" / name).read_bytes(), name)
    rows.append((name, want["verdict"], report.verdict, report.timings["total"]))

    assert report.verdict == want["verdict"], report.headline
    status = {f.key: f.status for f in report.fields}
    for key, wanted in want.get("field_status", {}).items():
        assert status.get(key) == wanted, f"{key}: {status}"
    types = {f.type for f in report.findings}
    for t in want.get("finding_types", []):
        assert t in types, f"missing finding {t}: {sorted(types)}"
    if want.get("critical_field"):
        assert any(f.severity == "critical" and f.field == want["critical_field"] for f in report.findings)
    if want.get("current_version"):
        assert report.current_version == want["current_version"]
    assert len(report.findings) >= want.get("min_findings", 0)
    assert report.timings["total"] < MAX_MS, report.timings
    text = (report.headline + " ".join(f.message for f in report.findings)).lower()
    assert not any(word in text for word in ("forg", "fake", "fraud"))  # we explain, we don't accuse


def test_expected_covers_all_files(demo):
    root, expected, _ = demo
    assert sorted(expected) == FILES
    assert all((root / "demo" / f).is_file() for f in FILES)
    assert expected["01_genuine.png"]["field_status"] == dict.fromkeys(
        ["name", "student_id", "grade", "program", "award", "date_issued"], "MATCH")
