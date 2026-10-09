"""One pass over the HTTP API: issue -> files -> verify -> registry -> reissue -> revoke, plus the error paths."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

FIELDS = {"name": "Ana Marie Dela Cruz", "student_id": "2023-00042", "program": "BA Communication",
          "award": "With Honors", "grade": "1.75", "date_issued": "2026-05-02"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_issue_verify_reissue_revoke(client):
    issued = client.post("/api/issue", json=FIELDS).json()
    png = client.get(issued["png_url"])
    assert png.status_code == 200 and client.get(issued["pdf_url"]).content[:5] == b"%PDF-"

    report = client.post("/api/verify", files={"file": ("cert.png", png.content, "image/png")}).json()
    assert report["verdict"] == "AUTHENTIC" and report["doc_id"] == issued["doc_id"]
    for url in report["images"].values():
        assert client.get(url).headers["content-type"] == "image/jpeg"

    v2 = client.post(f"/api/registry/{issued['doc_id']}/reissue", json={**FIELDS, "grade": "1.50"}).json()
    assert v2["version"] == 2
    old = client.post("/api/verify", files={"file": ("cert.png", png.content, "image/png")}).json()
    assert old["verdict"] == "REVOKED" and old["current_version"] == 2
    statuses = {e["version"]: e["status"] for e in client.get("/api/registry").json() if e["doc_id"] == issued["doc_id"]}
    assert statuses == {1: "superseded", 2: "active"}

    assert client.post(f"/api/registry/{issued['doc_id']}/revoke").json() == {"ok": True}
    new = client.post("/api/verify", files={"file": ("v2.png", client.get(v2["png_url"]).content, "image/png")}).json()
    assert new["verdict"] == "REVOKED" and new["current_version"] is None


def test_bad_requests(client):
    assert client.post("/api/issue", json={**FIELDS, "name": "x" * 61}).status_code == 422
    assert client.post("/api/issue", json={**FIELDS, "date_issued": "May 2"}).status_code == 422
    assert client.post("/api/verify", files={"file": ("x.png", b"not an image", "image/png")}).status_code == 400
    assert client.post("/api/verify", files={"file": ("empty.png", b"", "image/png")}).status_code == 400
    assert client.post("/api/issue", json={**FIELDS, "name": "   "}).status_code == 422
    assert client.post("/api/issue", json={**FIELDS, "date_issued": "2026-13-45"}).status_code == 422
    assert client.post("/api/issue", json={**FIELDS, "name": "王小明"}).status_code == 422
    assert client.post("/api/registry/00000000/revoke").status_code == 404
    assert client.post("/api/registry/..%2F..%2Fx/revoke").status_code in (404, 405)
    assert client.post("/api/registry/00000000/reissue", json=FIELDS).status_code == 404
    assert client.get("/reports/../../keys/issuer_ed25519.pem").status_code == 404
    assert client.get("/issued/registry.db").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/api/health").json() == {"ok": True, "ocr_engine": client.get("/api/health").json()["ocr_engine"], "offline": True}
