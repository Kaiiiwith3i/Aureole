"""End-to-end issue -> verify on TXT documents (no LibreOffice needed)."""
import cv2
import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR, convert, layout, pipeline, qr, seal, stamp
from core.registry import Registry
from devtools.photo_sim import simulate_photo

LETTER = """CERTIFICATE OF EMPLOYMENT

This certifies that Maria Clara Santos has been employed by
Lakeshore Trading Company as Senior Accountant since 2021-03-15.

Monthly salary: PHP 48,500.00
Employee number: 2021-00482

Issued upon request for whatever legal purpose it may serve.

Ramon Bautista
Human Resources Manager
"""
LONG = "\n".join(f"Line {i}: the quick brown fox jumps over the lazy dog." for i in range(1, 91))


def png(image: np.ndarray) -> bytes:
    return cv2.imencode(".png", image)[1].tobytes()


def jpg(image: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()


def issue(text: str = LETTER, name: str = "employment.txt") -> tuple[dict, bytes]:
    result = pipeline.issue(text.encode(), name)
    return result, result["pdf_path"].read_bytes()


def page_lines(result: dict, page: int = 0) -> list[dict]:
    import json
    return json.loads((result["pdf_path"].parent / "pages.json").read_text())[page]["lines"]


def retype(image: np.ndarray, line: dict, text: str) -> np.ndarray:
    """Paint the line white and print `text` in its place: what an edit in an image editor looks like."""
    x, y, w, h = line["bbox"]
    pil = Image.fromarray(image[:, :, ::-1].copy())
    draw = ImageDraw.Draw(pil)
    draw.rectangle([x - 4, y - 4, x + w + 4, y + h + 4], fill="white")
    font = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), 26)  # 11 pt source text at the frame's 0.85 scale, 200 DPI
    draw.text((x, y + h), text, font=font, fill="black", anchor="ls")
    return np.array(pil)[:, :, ::-1].copy()


def line_with(result: dict, needle: str) -> dict:
    return next(ln for ln in page_lines(result) if needle in ln["text"])


def test_issue_stores_files_and_row():
    result, pdf = issue()
    folder = result["pdf_path"].parent
    assert {p.name for p in folder.iterdir()} == {"issued.pdf", "source.txt", "pages.json"}
    entry = Registry().get(result["doc_id"])
    assert entry["status"] == "active" and entry["pages"] == 1 and entry["title"] == "employment"
    assert entry["content_sha256"].startswith(result["fingerprint"])
    lines = page_lines(result)
    assert any("Maria Clara Santos" in ln["text"] for ln in lines) and all(ln["readable"] for ln in lines)
    assert all(set(ln) == {"bbox", "text", "numeric", "readable"} for ln in lines)


def test_digital_exact_match():
    result, pdf = issue()
    report = pipeline.verify([("employment-sealed.pdf", pdf)])
    assert (report.mode, report.verdict, report.pages, report.pages_checked) == ("digital", "AUTHENTIC", [], [1])
    assert report.doc_id == result["doc_id"]


def test_clean_page_image_is_authentic():
    result, pdf = issue()
    report = pipeline.verify([("scan.png", png(stamp.render_page(pdf, 0)))])
    assert report.mode == "pages" and report.verdict == "AUTHENTIC", report.headline
    page = report.pages[0]
    assert page.page == 1 and page.lines == [] and page.lines_matched == page.lines_total > 5
    assert page.images.scan and page.images.expected


def test_photo_is_authentic():
    result, pdf = issue()
    photo = simulate_photo(stamp.render_page(pdf, 0), seed=3)
    report = pipeline.verify([("photo.jpg", jpg(photo))])
    assert report.verdict in ("AUTHENTIC", "AUTHENTIC_WITH_NOTES"), (report.headline, report.pages[0].lines)
    assert report.timings["total"] < 5000


@pytest.mark.parametrize("old,new", [("48,500.00", "98,500.00"), ("Santos", "Santoz")])
def test_edited_line_is_modified(old, new):
    result, pdf = issue()
    line = line_with(result, old)
    edited = retype(stamp.render_page(pdf, 0), line, line["text"].replace(old, new))
    report = pipeline.verify([("edited.png", png(edited))])
    assert report.verdict == "MODIFIED", report.headline
    page = report.pages[0]
    assert [r.status for r in page.lines] == ["MISMATCH"] and page.lines[0].expected == line["text"]
    assert any(f.severity == "critical" and f.line == page.lines[0].index for f in page.findings)


def test_added_text_is_modified():
    result, pdf = issue()
    image = stamp.render_page(pdf, 0)
    frame = layout.layout(False)
    x, y, w, h = frame.content
    blank = {"bbox": [x + 100, y + h - 300, 900, 40]}  # empty area near the bottom of the content box
    edited = retype(image, blank, "Approved loan amount: PHP 950,000.00")
    report = pipeline.verify([("added.png", png(edited))])
    assert report.verdict == "MODIFIED", report.headline
    assert any(f.type == "text_change" and f.line is None for f in report.pages[0].findings)


def test_seal_transplanted_onto_another_document():
    result, pdf = issue()
    other, _ = convert.to_pdf(LONG[:1800].encode(), "other.txt")
    forged = stamp.render_page(stamp.stamp(other, "ffffffff", 1, Ed25519PrivateKey.generate(), "2026-01-01"), 0)
    genuine = stamp.render_page(pdf, 0)
    x, y, w, h = layout.layout(False).content
    out = genuine.copy()  # the genuine frame (markers, seal, footer) around someone else's content
    out[y:y + h, x:x + w] = forged[y:y + h, x:x + w]
    report = pipeline.verify([("transplant.png", png(out))])
    assert report.verdict == "MODIFIED", report.headline
    assert report.headline == pipeline.HEADLINES["different"]


def test_revoked_and_superseded():
    result, pdf = issue()
    again = pipeline.reissue(result["doc_id"], LETTER.replace("48,500", "52,000").encode(), "employment.txt")
    assert again["version"] == 2
    old = pipeline.verify([("v1.pdf", pdf)])
    assert (old.verdict, old.current_version) == ("REVOKED", 2)
    scan = pipeline.verify([("v1.png", png(stamp.render_page(pdf, 0)))])
    assert scan.verdict == "REVOKED" and "version 2" in scan.headline
    assert pipeline.revoke(result["doc_id"])
    new = pipeline.verify([("v2.pdf", again["pdf_path"].read_bytes())])
    assert new.verdict == "REVOKED" and "revoked" in new.headline
    with pytest.raises(KeyError):
        pipeline.reissue("00000000", b"x", "x.txt")


def test_missing_page_is_inconclusive():
    result, pdf = issue(LONG, "long.txt")
    assert result["pages"] >= 2
    one = pipeline.verify([("p1.png", png(stamp.render_page(pdf, 0)))])
    assert one.verdict == "INCONCLUSIVE" and one.pages[0].verdict == "AUTHENTIC" and one.pages_checked == [1]
    every = pipeline.verify([(f"p{i}.png", png(stamp.render_page(pdf, i))) for i in range(result["pages"])])
    assert every.verdict == "AUTHENTIC" and every.pages_checked == list(range(1, result["pages"] + 1))


def test_page_from_another_document():
    a, pdf_a = issue(LONG, "a.txt")
    b, pdf_b = issue(LONG.replace("fox", "cat"), "b.txt")
    report = pipeline.verify([("a1.png", png(stamp.render_page(pdf_a, 0))), ("b2.png", png(stamp.render_page(pdf_b, 1)))])
    assert report.verdict == "MODIFIED" and report.pages[1].headline == pipeline.HEADLINES["other_doc"]
    assert report.pages_checked == [1]


def test_not_issued():
    plain, _ = convert.to_pdf(LETTER.encode(), "plain.txt")
    report = pipeline.verify([("plain.pdf", plain)])
    assert report.verdict == "NOT_ISSUED" and report.doc_id is None
    foreign = np.full((1200, 900, 3), 255, np.uint8)  # a QR that belongs to the document, not to Signet
    foreign[100:400, 100:400] = cv2.cvtColor(qr.render_qr("upi://pay?to=someone", 300), cv2.COLOR_GRAY2BGR)
    assert pipeline.verify([("invoice.png", png(foreign))]).verdict == "NOT_ISSUED"


def test_valid_signature_without_registry_record():
    key, _ = seal.load_or_create_issuer_key()
    content, _ = convert.to_pdf(LETTER.encode(), "x.txt")
    pdf = stamp.stamp(content, "0badf00d", 1, key, "2026-01-01")  # signed by the real key, never registered
    report = pipeline.verify([("x.pdf", pdf)])
    assert report.verdict == "NOT_ISSUED" and report.headline == pipeline.HEADLINES["no_record"]


def test_untrusted_key():
    content, _ = convert.to_pdf(LETTER.encode(), "x.txt")
    pdf = stamp.stamp(content, "0badf00d", 1, Ed25519PrivateKey.generate(), "2026-01-01")
    assert pipeline.verify([("x.pdf", pdf)]).verdict == "INVALID_SEAL"


def test_bad_uploads():
    for data in (b"", b"not an image", b"%PDF-1.7 broken"):
        with pytest.raises(ValueError):
            pipeline.verify([("bad", data)])
    with pytest.raises(ValueError):
        pipeline.issue(b"\x00\x01\x02", "blob.bin")


def test_added_text_skips_ocr_on_thin_non_text_region():
    from core.diff import Region
    image = np.full((20, 1200, 3), 255, np.uint8)
    region = Region((0, 0, 1200, 8), np.full((8, 1200), 255, np.uint8), 9600, 1.0)
    assert pipeline._added_text(image, region) == 0.0


def test_qr_only_page_is_inconclusive_instead_of_false_modified():
    result, pdf = issue()
    image = stamp.render_page(pdf, 0)
    for x, y in layout.layout(False).markers.values():
        cv2.rectangle(image, (x - 3, y - 3), (x + layout.MARKER + 3, y + layout.MARKER + 3), (255, 255, 255), -1)
    photo = simulate_photo(image, seed=3)
    report = pipeline.verify([("marker-hidden.jpg", jpg(photo))])
    assert report.verdict == "INCONCLUSIVE" and "corners" in report.headline
    assert report.pages[0].lines == [] and report.pages[0].findings == []


def test_translucent_stamp_over_text_is_not_modified():
    from devtools.tamper import add_stamp
    result, pdf = issue()
    line = line_with(result, "48,500")
    x, y, w, h = line["bbox"]
    image, _ = add_stamp(stamp.render_page(pdf, 0), (x + w // 2, y + h // 2), 80, seed=3)
    report = pipeline.verify([("stamped.png", png(image))])
    assert report.verdict in ("AUTHENTIC_WITH_NOTES", "INCONCLUSIVE")


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_stamp_in_a_photo_is_a_note_not_a_modification(seed):
    """The stamp's own lettering is not added printed text, and a stamp lying across several lines only makes them unreadable."""
    from devtools.tamper import add_stamp
    result, pdf = issue()
    page = stamp.render_page(pdf, 0)
    blank, _ = add_stamp(page, (500, 1500), 200, seed=5)
    report = pipeline.verify([("stamped.jpg", jpg(simulate_photo(blank, seed=seed)))])
    assert report.verdict == "AUTHENTIC_WITH_NOTES", report.headline
    assert any(f.type == "stamp" for f in report.pages[0].findings)
    x, y, w, h = line_with(result, "48,500")["bbox"]
    across, _ = add_stamp(page, (x + w // 2, y + h // 2), 90, seed=3)
    report = pipeline.verify([("stamped.jpg", jpg(simulate_photo(across, seed=seed)))])
    assert report.verdict == "INCONCLUSIVE", (report.headline, report.pages[0].lines)
    assert not any(line.status == "MISMATCH" for line in report.pages[0].lines)


def test_damage_beside_a_line_is_never_a_mismatch():
    """QA: a stamp or stain centred on one line garbled its neighbours, which carried none of the mark's own ink."""
    from devtools.tamper import add_stain, add_stamp
    result, pdf = issue()
    page = stamp.render_page(pdf, 0)
    x, y, w, h = page_lines(result)[1]["bbox"]
    for marked in (add_stamp(page, (x + w // 2, y + h // 2), 120, seed=2)[0], add_stain(page, (x + w // 2, y + h // 2), 150, seed=2)[0]):
        report = pipeline.verify([("damaged.jpg", jpg(simulate_photo(marked, seed=7)))])
        assert report.verdict in ("AUTHENTIC_WITH_NOTES", "INCONCLUSIVE"), (report.headline, report.pages[0].lines)
        assert not any(line.status == "MISMATCH" for line in report.pages[0].lines)


def test_added_code_or_unexplained_mark_is_never_plain_authentic():
    result, pdf = issue()
    page = stamp.render_page(pdf, 0)
    coded = page.copy()  # a payment QR pasted onto blank paper: the kind of thing a fraudster adds
    coded[1200:1500, 900:1200] = cv2.cvtColor(qr.render_qr("https://example.com/pay?id=12345", 300), cv2.COLOR_GRAY2BGR)
    for data in (png(coded), jpg(simulate_photo(coded, seed=4))):
        report = pipeline.verify([("coded", data)])
        assert report.verdict == "MODIFIED" and report.headline == pipeline.HEADLINES["code"], report.headline
    barred = page.copy()
    cv2.rectangle(barred, (400, 1300), (1000, 1400), (0, 0, 0), -1)
    report = pipeline.verify([("barred.png", png(barred))])
    assert report.verdict == "AUTHENTIC_WITH_NOTES", report.headline
    assert any(f.severity == "warning" and "added" in f.message for f in report.pages[0].findings)
    # every finding shown as critical must also decide the verdict
    for r in (report, pipeline.verify([("clean.png", png(page))])):
        assert not any(f.severity == "critical" for f in r.pages[0].findings)
