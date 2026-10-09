"""Build v2 demonstration pages from the current document sealing pipeline."""
import json
from pathlib import Path

import cv2
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core import convert, layout, pipeline, stamp
from devtools import tamper
from devtools.photo_sim import save_jpeg, simulate_photo

TEXT = """EMPLOYMENT CONFIRMATION

This confirms that Avery Stone works for Lakeshore Trading Company.
Position: Senior Accountant
Monthly salary: PHP 48,500.00
Employee number: 2021-00482

Issued for reference on 10 October 2026.

Ramon Bautista
Human Resources Manager
"""


def build_demo_set(out_dir: Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    issued = pipeline.issue(TEXT.encode(), "employment.txt", "Employment confirmation")
    pdf = issued["pdf_path"].read_bytes()
    page = stamp.render_page(pdf, 0)
    lines = json.loads((issued["pdf_path"].parent / "pages.json").read_text())[0]["lines"]
    salary = next(line for line in lines if "48,500" in line["text"])
    name = next(line for line in lines if "Avery Stone" in line["text"])
    cases = {}

    def save(name, image, verdict, photo=False):
        path = out / name
        if photo:
            save_jpeg(simulate_photo(image, seed=len(cases) + 11), path)
        elif not cv2.imwrite(str(path), image):
            raise OSError(f"could not write {path}")
        cases[name] = {"verdict": verdict}

    save("01_genuine.png", page, "AUTHENTIC")
    save("02_genuine_photo.jpg", page, "AUTHENTIC", True)
    worn, _ = tamper.add_stain(page, (900, 1700), 140, seed=3)
    worn, _ = tamper.add_fold(worn, 0.82, True, seed=4)
    save("03_stained_folded.jpg", worn, "AUTHENTIC_WITH_NOTES", True)
    marked, _ = tamper.add_stamp(page, (430, 1700), 110, seed=5)
    marked, _ = tamper.add_scribble(marked, [900, 1850, 400, 90], seed=6)
    save("04_stamped_annotated.jpg", marked, "AUTHENTIC_WITH_NOTES", True)
    edited, _ = tamper.retype_line(page, salary["bbox"], salary["text"].replace("48,500", "98,500"))
    save("05_salary_edited.png", edited, "MODIFIED")
    renamed, _ = tamper.retype_line(page, name["bbox"], name["text"].replace("Avery", "Blake"))
    save("06_name_edited_photo.jpg", renamed, "MODIFIED", True)
    older = pipeline.issue(TEXT.encode(), "older-employment.txt")
    old_page = stamp.render_page(older["pdf_path"].read_bytes(), 0)
    pipeline.reissue(older["doc_id"], TEXT.replace("48,500", "52,000").encode(), "employment.txt")
    save("07_superseded.png", old_page, "REVOKED")
    content, _ = convert.to_pdf(TEXT.encode(), "employment.txt")
    rogue = stamp.stamp(content, "0badf00d", 1, Ed25519PrivateKey.generate(), "2026-10-10")
    save("08_untrusted_seal.png", stamp.render_page(rogue, 0), "INVALID_SEAL")
    smudged, _ = tamper.smudge_line(page, salary["bbox"], seed=7)
    save("09_smudged_line.jpg", smudged, "INCONCLUSIVE", True)
    save("10_unsealed.png", stamp.render_page(content, 0), "NOT_ISSUED")
    (out / "expected.json").write_text(json.dumps(cases, indent=2))
    return cases
