"""FastAPI app: API under /api, report and issued files, and the static UI from web/. No external URLs anywhere."""
import hmac
import os
import re
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.schemas import ApprovalResponse, Health, IssueResponse, Login, RegistryEntry, Report
from core import KEYS_DIR, ROOT, convert, data_dir, layout, ocr, pipeline, seal
from core.registry import Registry

MAX_UPLOAD = 25 * 1024 * 1024  # per request, all files together
DOC_ID = r"^[0-9a-f]{8}$"
ISSUED_FILE = re.compile(r"^([0-9a-f]{8}_v\d{1,4})\.pdf$")
REPORT_ID = re.compile(r"^[0-9a-f]{12}$")
REPORT_FILE = re.compile(r"^\d{1,2}_(scan|expected|diff|ela)\.jpg$")
APPROVED_FILE = re.compile(r"^upload_\d{1,2}\.(pdf|png|jpg|jpeg)$")
COOKIE = "signet_staff"

_sessions: set[str] = set()  # ponytail: in memory, so a restart signs staff out; persist if that ever matters


def staff_password() -> str:
    """Env SIGNET_STAFF_PASSWORD, else a password generated once into keys/staff_password.txt (mode 600)."""
    if os.environ.get("SIGNET_STAFF_PASSWORD"):
        return os.environ["SIGNET_STAFF_PASSWORD"]
    path = KEYS_DIR / "staff_password.txt"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(12))
        path.chmod(0o600)
    return path.read_text().strip()


def is_staff(request: Request) -> bool:
    return request.cookies.get(COOKIE) in _sessions


def staff(request: Request) -> None:
    if not is_staff(request):
        raise HTTPException(401, "Staff sign-in required.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    seal.load_or_create_issuer_key()
    staff_password()
    await run_in_threadpool(ocr.warm_up)  # first verify is as fast as the rest
    yield


# docs_url/redoc_url off: FastAPI's doc pages load assets from a CDN, and this app promises zero external URLs.
app = FastAPI(title="Signet", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def revalidate(request, call_next):
    """Local app: always revalidate, so an updated UI or a re-issued file is never served stale from the browser cache."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


def _read(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    out, left = [], MAX_UPLOAD
    for f in files:
        data = f.file.read(left + 1)
        left -= len(data)
        if left < 0:
            raise HTTPException(413, "These files are larger than 25 MB together.")
        out.append((f.filename or "upload", data))
    return out


def _issued(result: dict) -> IssueResponse:
    return IssueResponse(**{k: result[k] for k in ("doc_id", "version", "title", "pages", "fingerprint")},
                         pdf_url=f"/issued/{result['doc_id']}_v{result['version']}.pdf")


@app.get("/api/health")
def health() -> Health:
    return Health(ok=True, ocr_engine=ocr.engine_name(), converter=convert.has_converter())


@app.post("/api/login")
def login(body: Login, response: Response) -> dict:
    if not hmac.compare_digest(body.password.encode(), staff_password().encode()):
        time.sleep(0.5)  # slows guessing; the default password is random
        raise HTTPException(401, "Wrong password.")
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict:
    _sessions.discard(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request) -> dict:
    return {"staff": is_staff(request)}


@app.post("/api/issue", dependencies=[Depends(staff)])
def issue(file: UploadFile = File(...), title: str = Form("")) -> IssueResponse:
    (name, data), = _read([file])
    try:
        return _issued(pipeline.issue(data, name, title))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/verify")
def verify(request: Request, files: list[UploadFile] = File(...)) -> Report:
    if len(files) > layout.MAX_PAGES:
        raise HTTPException(400, f"Send at most {layout.MAX_PAGES} files at a time.")
    try:
        report = pipeline.verify(_read(files))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not is_staff(request):  # someone who only holds a seal must not get the original's content back
        for page in report.pages:
            page.images.expected = None
            for line in page.lines:
                line.expected = None
    return report


@app.get("/api/registry", dependencies=[Depends(staff)])
def registry() -> list[RegistryEntry]:
    keys = ("doc_id", "version", "kid", "title", "source_name", "source_type", "pages", "status", "issued_at", "current_version")
    db = Registry()
    return [RegistryEntry(**{k: e[k] for k in keys}, fingerprint=e["content_sha256"][:16],
                          pdf_url=f"/issued/{e['doc_id']}_v{e['version']}.pdf",
                          approved_copies=len(db.approvals(e["doc_id"], e["version"]))) for e in db.list()]


@app.post("/api/registry/{doc_id}/revoke", dependencies=[Depends(staff)])
def revoke(doc_id: str) -> dict:
    if not re.match(DOC_ID, doc_id) or not pipeline.revoke(doc_id):
        raise HTTPException(404, "Unknown document.")
    return {"ok": True}


@app.post("/api/registry/{doc_id}/reissue", dependencies=[Depends(staff)])
def reissue(doc_id: str, file: UploadFile = File(...), title: str = Form("")) -> IssueResponse:
    (name, data), = _read([file])
    try:
        return _issued(pipeline.reissue(doc_id, data, name, title))
    except KeyError:
        raise HTTPException(404, "Unknown document.")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/registry/{doc_id}/approve", dependencies=[Depends(staff)])
def approve_signed(doc_id: str, files: list[UploadFile] = File(...)) -> ApprovalResponse:
    if not re.match(DOC_ID, doc_id) or Registry().get(doc_id) is None:
        raise HTTPException(404, "Unknown document.")
    if len(files) > layout.MAX_PAGES:
        raise HTTPException(400, f"Send at most {layout.MAX_PAGES} files at a time.")
    try:
        result = pipeline.approve_signed(doc_id, _read(files))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return ApprovalResponse(**result)


@app.get("/api/registry/{doc_id}/approved", dependencies=[Depends(staff)])
def approved_copies(doc_id: str) -> list[dict]:
    if not re.match(DOC_ID, doc_id) or Registry().get(doc_id) is None:
        raise HTTPException(404, "Unknown document.")
    out = []
    db = Registry()
    for version in db.list():
        if version["doc_id"] != doc_id:
            continue
        for approval in db.approvals(doc_id, version["version"]):
            folder = data_dir() / "approved" / approval["id"]
            out.append({"id": approval["id"], "version": approval["version"], "approved_at": approval["approved_at"],
                        "files": [f"/approved/{approval['id']}/{p.name}" for p in sorted(folder.glob("upload_*"))]})
    return out


@app.get("/approved/{approval_id}/{name}", dependencies=[Depends(staff)])
def approved_file(approval_id: str, name: str) -> FileResponse:
    if not REPORT_ID.match(approval_id) or not APPROVED_FILE.match(name):
        raise HTTPException(404)
    path = data_dir() / "approved" / approval_id / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=name)


# Files are served through routes (not mounts) so SIGNET_DATA_DIR is read per request and names are validated.
@app.get("/issued/{name}", dependencies=[Depends(staff)])
def issued_file(name: str) -> FileResponse:
    m = ISSUED_FILE.match(name)
    path = data_dir() / "issued" / (m.group(1) if m else "") / "issued.pdf"
    if not m or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=name)


@app.get("/reports/{report_id}/{name}")
def report_file(request: Request, report_id: str, name: str) -> FileResponse:
    m = REPORT_FILE.match(name)
    path = data_dir() / "reports" / report_id / name
    if not REPORT_ID.match(report_id) or not m or not path.is_file():
        raise HTTPException(404)
    if m.group(1) == "expected":
        staff(request)
    return FileResponse(path)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
