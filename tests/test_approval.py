"""Staff approval recognizes a signed copy without changing the unsigned original."""
from io import BytesIO

import cv2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from core import pipeline, stamp
from devtools.photo_sim import simulate_photo
from devtools.tamper import add_scribble, retype_line
from tests.test_pipeline import LETTER, LONG, line_with, retype


def photo(image, seed):
    return cv2.imencode(".jpg", simulate_photo(image, seed=seed), [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()


def scanned_pdf(image, seed):
    out = BytesIO()
    photo_image = simulate_photo(image, seed=seed)
    Image.fromarray(cv2.cvtColor(photo_image, cv2.COLOR_BGR2RGB)).save(out, format="PDF", resolution=200)
    return out.getvalue()


def test_approve_signed_copy_and_recapture():
    issued = pipeline.issue(LETTER.encode(), "letter.txt")
    pdf = issued["pdf_path"].read_bytes()
    base = stamp.render_page(pdf, 0)
    signed, _ = add_scribble(base, [500, 1700, 480, 85], seed=6)
    first, second = photo(signed, 11), photo(signed, 12)
    with pytest.raises(ValueError, match="No added signature"):
        pipeline.approve_signed(issued["doc_id"], [("unsigned.jpg", photo(base, 10))])
    approval = pipeline.approve_signed(issued["doc_id"], [("signed.jpg", first)])

    assert pipeline.approve_signed(issued["doc_id"], [("signed.jpg", first)])["id"] == approval["id"]
    exact = pipeline.verify([("signed.jpg", first)])
    assert (exact.mode, exact.approval_id, exact.verdict) == ("approved", approval["id"], "AUTHENTIC_WITH_NOTES")
    recapture = pipeline.verify([("recapture.jpg", second)])
    assert recapture.approval_id == approval["id"] and recapture.verdict == "AUTHENTIC_WITH_NOTES"
    assert pipeline.verify([("unsigned.pdf", pdf)]).verdict == "AUTHENTIC"

    for seed in (8, 9):
        other, _ = add_scribble(base, [500, 1700, 480, 85], seed=seed)
        assert pipeline.verify([("different.jpg", photo(other, seed + 30))]).approval_id is None
    extra, _ = add_scribble(signed, [1000, 1850, 260, 70], seed=3)
    assert pipeline.verify([("extra.jpg", photo(extra, 13))]).approval_id is None

    salary = line_with(issued, "48,500")
    changed = retype(base, salary, salary["text"].replace("48,500", "98,500"))
    changed, _ = add_scribble(changed, [500, 1700, 480, 85], seed=6)
    tampered = photo(changed, 12)
    assert pipeline.verify([("tampered.jpg", tampered)]).approval_id is None
    with pytest.raises(ValueError, match="match its issued text"):
        pipeline.approve_signed(issued["doc_id"], [("tampered.jpg", tampered)])


def test_approval_api_requires_staff_and_returns_id(monkeypatch):
    monkeypatch.setenv("SIGNET_STAFF_PASSWORD", "approval-test-password")
    with TestClient(app) as client:
        assert client.post("/api/registry/00000000/approve", files=[("files", ("x.jpg", b"x"))]).status_code == 401
        assert client.post("/api/login", json={"password": "approval-test-password"}).status_code == 200
        issued = pipeline.issue(LETTER.encode(), "letter.txt")
        page = stamp.render_page(issued["pdf_path"].read_bytes(), 0)
        signed, _ = add_scribble(page, [500, 1700, 480, 85], seed=6)
        data = photo(signed, 11)
        response = client.post(f"/api/registry/{issued['doc_id']}/approve", files=[("files", ("signed.jpg", data, "image/jpeg"))])
        assert response.status_code == 200, response.text
        approval_id = response.json()["id"]
        row = next(r for r in client.get("/api/registry").json() if r["doc_id"] == issued["doc_id"])
        assert row["approved_copies"] == 1
        approved = client.get(f"/api/registry/{issued['doc_id']}/approved").json()
        assert approved[0]["id"] == approval_id and len(approved[0]["files"]) == 1
        assert client.get(approved[0]["files"][0]).content == data
        client.post("/api/logout")
        assert client.get(approved[0]["files"][0]).status_code == 401
        public = client.post("/api/verify", files=[("files", ("signed.jpg", data, "image/jpeg"))]).json()
        assert public["approval_id"] == approval_id and public["mode"] == "approved"


def test_all_pages_required_and_only_one_page_needs_a_signature():
    issued = pipeline.issue(LONG.encode(), "two-pages.txt")
    pdf = issued["pdf_path"].read_bytes()
    assert issued["pages"] == 2
    first, second = [], []
    for i in range(2):
        page = stamp.render_page(pdf, i)
        if i == 1:
            page, _ = add_scribble(page, [500, 1700, 480, 85], seed=6)
        first.append((f"page-{i+1}.jpg", photo(page, 11 + i)))
        second.append((f"page-{i+1}.jpg", photo(page, 12 + i)))
    with pytest.raises(ValueError, match="full document"):
        pipeline.approve_signed(issued["doc_id"], first[:1])
    approval = pipeline.approve_signed(issued["doc_id"], first)
    assert pipeline.verify(second).approval_id == approval["id"]


def test_scanned_pdf_can_be_approved_and_recaptured():
    issued = pipeline.issue(LETTER.encode(), "letter.txt")
    page = stamp.render_page(issued["pdf_path"].read_bytes(), 0)
    signed, _ = add_scribble(page, [500, 1700, 480, 85], seed=6)
    approval = pipeline.approve_signed(issued["doc_id"], [("signed.pdf", scanned_pdf(signed, 11))])
    report = pipeline.verify([("recapture.pdf", scanned_pdf(signed, 12))])
    assert report.approval_id == approval["id"]


def test_approval_never_covers_something_added_later():
    """A big approved signature must not hide a short printed amount or a small pen mark added afterwards."""
    issued = pipeline.issue(LETTER.encode(), "letter.txt")
    base = stamp.render_page(issued["pdf_path"].read_bytes(), 0)
    signed, _ = add_scribble(base, [250, 1500, 1100, 220], seed=6)
    signed, _ = add_scribble(signed, [250, 1760, 1100, 220], seed=9)
    forged, _ = retype_line(signed, [322, 1206, 300, 40], "PHP 950,000")
    assert pipeline.verify([("forged.jpg", photo(forged, 12))]).verdict == "MODIFIED"

    approval = pipeline.approve_signed(issued["doc_id"], [("signed.jpg", photo(signed, 11))])
    assert pipeline.verify([("recapture.jpg", photo(signed, 12))]).approval_id == approval["id"]
    after = pipeline.verify([("forged.jpg", photo(forged, 12))])
    assert (after.verdict, after.approval_id) == ("MODIFIED", None), after.headline
    assert after.pages[0].verdict == "MODIFIED"
    noted, _ = add_scribble(signed, [1250, 1250, 170, 60], seed=4)
    assert pipeline.verify([("noted.jpg", photo(noted, 12))]).approval_id is None
