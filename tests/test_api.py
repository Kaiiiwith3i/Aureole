"""HTTP layer: staff gate, redaction for the public, file routes."""
import cv2
import pytest
from fastapi.testclient import TestClient

from core import stamp
from tests.test_pipeline import LETTER, line_with, png, retype

PASSWORD = "test-staff-password"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SIGNET_STAFF_PASSWORD", PASSWORD)
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client) -> None:
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200


def issue(client) -> dict:
    r = client.post("/api/issue", files={"file": ("employment.txt", LETTER.encode(), "text/plain")}, data={"title": ""})
    assert r.status_code == 200, r.text
    return r.json()


def test_staff_gate(client):
    assert client.get("/api/me").json() == {"staff": False}
    assert client.post("/api/issue", files={"file": ("a.txt", b"hello")}).status_code == 401
    assert client.get("/api/registry").status_code == 401
    assert client.post("/api/registry/a1b2c3d4/revoke").status_code == 401
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    login(client)
    assert client.get("/api/me").json() == {"staff": True}
    client.post("/api/logout")
    assert client.get("/api/registry").status_code == 401


def test_issue_registry_revoke_reissue(client):
    login(client)
    doc = issue(client)
    assert doc["pages"] == 1 and doc["title"] == "employment" and len(doc["fingerprint"]) == 16
    pdf = client.get(doc["pdf_url"])
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    row, = client.get("/api/registry").json()
    assert row["doc_id"] == doc["doc_id"] and row["status"] == "active" and row["source_type"] == "txt"
    again = client.post(f"/api/registry/{doc['doc_id']}/reissue", files={"file": ("employment.txt", LETTER.replace("48,500", "52,000").encode())})
    assert again.json()["version"] == 2
    assert client.post(f"/api/registry/{doc['doc_id']}/revoke").json() == {"ok": True}
    assert client.post("/api/registry/00000000/revoke").status_code == 404
    assert client.post("/api/issue", files={"file": ("x.bin", b"\x00\x01")}).status_code == 422
    client.post("/api/logout")
    assert client.get(doc["pdf_url"]).status_code == 401


def test_public_verify_hides_the_original(client):
    login(client)
    doc = issue(client)
    pdf = client.get(doc["pdf_url"]).content
    from core import pipeline
    line = line_with({"pdf_path": pipeline.issued_dir(doc["doc_id"], 1) / "issued.pdf"}, "48,500.00")
    edited = png(retype(stamp.render_page(pdf, 0), line, line["text"].replace("48,500.00", "98,500.00")))

    staff = client.post("/api/verify", files=[("files", ("edited.png", edited, "image/png"))]).json()
    assert staff["verdict"] == "MODIFIED" and staff["pages"][0]["lines"][0]["expected"] == line["text"]
    assert client.get(staff["pages"][0]["images"]["expected"]).status_code == 200

    client.post("/api/logout")
    public = client.post("/api/verify", files=[("files", ("edited.png", edited, "image/png"))]).json()
    page = public["pages"][0]
    assert public["verdict"] == "MODIFIED" and page["lines"][0]["expected"] is None and page["images"]["expected"] is None
    assert "48,500" not in str(public)
    assert client.get(page["images"]["scan"]).status_code == 200
    assert client.get(page["images"]["scan"].replace("scan", "expected")).status_code == 401
    assert client.post("/api/verify", files=[("files", ("sealed.pdf", pdf, "application/pdf"))]).json()["mode"] == "digital"


def test_upload_errors(client):
    assert client.post("/api/verify", files=[("files", ("x.png", b"junk"))]).status_code == 400
    assert client.post("/api/verify", files=[("files", (f"{i}.png", b"x")) for i in range(11)]).status_code == 400
    assert client.get("/reports/000000000000/1_scan.jpg").status_code == 404
    assert client.get("/reports/..%2f..%2fkeys/1_scan.jpg").status_code == 404
    health = client.get("/api/health").json()
    assert health["ok"] and health["offline"] and isinstance(health["converter"], bool)
