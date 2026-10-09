"""Builds the 10 demo files + expected.json. Sealed documents are issued through core.pipeline into data_dir()."""
import json
import shutil
from pathlib import Path

import cv2

from core import pipeline
from core.template import load_template, render_certificate, save_png, zones
from devtools import tamper
from devtools.photo_sim import save_jpeg, simulate_photo

# All fictional.
MARIA = {"name": "Maria Clara Santos", "student_id": "2024-10482", "grade": "1.45", "program": "BS Computer Science",
         "award": "Dean's Lister", "date_issued": "2026-03-14"}
JOSE = {"name": "Jose Protacio Rivera", "student_id": "2023-07731", "grade": "2.75", "program": "BS Information Technology",
        "award": "Certificate of Completion", "date_issued": "2026-03-14"}
DEFAULTS = {"field_status": {}, "finding_types": [], "critical_field": None, "current_version": None, "min_findings": 0}


def build_demo_set(out_dir: Path) -> dict:
    """Write 01_genuine.png ... 10_no_seal_edited.jpg and expected.json into out_dir; return the expected dict.

    expected.json: {"<file>": {"verdict": str, "field_status": {key: status} (only what must be asserted),
                               "finding_types": [types that must appear], "critical_field": key | null,
                               "current_version": int | null, "min_findings": int}}
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    free = load_template()["free_areas"]
    expected: dict[str, dict] = {}

    def case(name: str, verdict: str, **extra) -> Path:
        expected[name] = {**DEFAULTS, "verdict": verdict, **extra}
        return out / name

    base = pipeline.issue(MARIA)
    page = cv2.imread(str(base["png_path"]))

    shutil.copy(base["png_path"], case("01_genuine.png", "AUTHENTIC", field_status=dict.fromkeys(MARIA, "MATCH")))
    save_jpeg(simulate_photo(page, seed=11), case("02_genuine_photo.jpg", "AUTHENTIC"))

    worn, _ = tamper.add_stain(page, (1480, 1010), 150, seed=3)
    worn, _ = tamper.add_fold(worn, 0.3, True, seed=4)
    save_jpeg(simulate_photo(worn, seed=12), case("03_stained_folded.jpg", "AUTHENTIC_WITH_NOTES", finding_types=["physical_damage", "fold"]))

    sx, sy, sw, sh = free["stamp"]
    marked, _ = tamper.add_stamp(page, (sx + sw // 2, sy + sh // 2), 120, seed=5)
    marked, _ = tamper.add_scribble(marked, free["scribble"], seed=6)
    save_jpeg(simulate_photo(marked, seed=13), case("04_stamped_annotated.jpg", "AUTHENTIC_WITH_NOTES", finding_types=["stamp", "handwriting"]))

    edited, _ = tamper.retype_field(page, "grade", "1.00")
    save_png(edited, case("05_grade_edited.png", "MISMATCH", field_status={"grade": "MISMATCH"}, critical_field="grade"))

    renamed, _ = tamper.retype_field(page, "name", "Marco Dela Vega")
    save_jpeg(simulate_photo(renamed, seed=14), case("06_name_edited_photo.jpg", "MISMATCH", field_status={"name": "MISMATCH"}))

    old = pipeline.issue(JOSE)
    pipeline.reissue(old["doc_id"], {**JOSE, "grade": "2.50"})  # corrected grade supersedes v1
    shutil.copy(old["png_path"], case("07_revoked.png", "REVOKED", current_version=2))

    # a forger's best attempt: same document id, better grade, QR re-signed with their own key
    save_png(tamper.rogue_reseal({**MARIA, "grade": "1.00"}, base["doc_id"]), case("08_untrusted_seal.png", "INVALID_SEAL"))

    smudged, _ = tamper.smudge_field(page, "student_id", seed=7)
    save_jpeg(smudged, case("09_smudged_field.jpg", "INCONCLUSIVE", field_status={"student_id": "UNREADABLE"}))

    plain = render_certificate(MARIA, {"seal": None, "markers": False, "doc_id": "", "version": 0})
    x, y, w, h = zones()["student_id"]["bbox"]
    copied, _ = tamper.copy_move(plain, [x - 10, y - 60, 1200, 150], (x - 10, 1360))  # label+values row pasted lower down
    save_jpeg(copied, case("10_no_seal_edited.jpg", "NO_SEAL", min_findings=1))

    (out / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    return expected
