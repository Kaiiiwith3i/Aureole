"""FastAPI app: API under /api, report and issued files, and the static UI from web/. No external URLs anywhere."""
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.schemas import CertFields, Health, IssueResponse, RegistryEntry, Report
from core import ROOT, data_dir, ocr, pipeline, seal
from core.registry import Registry

MAX_UPLOAD = 25 * 1024 * 1024
DOC_ID = r"^[0-9a-f]{8}$"
ISSUED_FILE = re.compile(r"^[0-9a-f]{8}_v\d{1,4}\.(png|pdf)$")
REPORT_ID = re.compile(r"^[0-9a-f]{12}$")
REPORT_FILE = {"scan.jpg", "expected.jpg", "diff.jpg", "ela.jpg"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    seal.load_or_create_issuer_key()
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


def _urls(doc_id: str, version: int) -> dict:
    return {"png_url": f"/issued/{doc_id}_v{version}.png", "pdf_url": f"/issued/{doc_id}_v{version}.pdf"}


def _issued(result: dict) -> IssueResponse:
    return IssueResponse(doc_id=result["doc_id"], version=result["version"], **_urls(result["doc_id"], result["version"]))


@app.get("/api/health")
def health() -> Health:
    return Health(ok=True, ocr_engine=ocr.engine_name())


@app.post("/api/issue")
def issue(fields: CertFields) -> IssueResponse:
    try:
        return _issued(pipeline.issue(fields.model_dump()))
    except ValueError as e:  # e.g. seal too long for the QR
        raise HTTPException(422, str(e))


@app.post("/api/verify")
def verify(file: UploadFile = File(...)) -> Report:
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 25 MB.")
    try:
        return pipeline.verify(data, (file.filename or "upload")[:120])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/registry")
def registry() -> list[RegistryEntry]:
    return [RegistryEntry(**{k: e[k] for k in ("doc_id", "version", "kid", "fields", "status", "issued_at", "current_version")},
                          **_urls(e["doc_id"], e["version"])) for e in Registry().list()]


@app.post("/api/registry/{doc_id}/revoke")
def revoke(doc_id: str) -> dict:
    if not re.match(DOC_ID, doc_id) or not pipeline.revoke(doc_id):
        raise HTTPException(404, "Unknown document.")
    return {"ok": True}


@app.post("/api/registry/{doc_id}/reissue")
def reissue(doc_id: str, fields: CertFields) -> IssueResponse:
    try:
        return _issued(pipeline.reissue(doc_id, fields.model_dump()))
    except KeyError:
        raise HTTPException(404, "Unknown document.")
    except ValueError as e:
        raise HTTPException(422, str(e))


# Files are served through routes (not mounts) so SIGNET_DATA_DIR is read per request and names are validated.
@app.get("/issued/{name}")
def issued_file(name: str) -> FileResponse:
    path = data_dir() / "issued" / name
    if not ISSUED_FILE.match(name) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/reports/{report_id}/{name}")
def report_file(report_id: str, name: str) -> FileResponse:
    path = data_dir() / "reports" / report_id / name
    if not REPORT_ID.match(report_id) or name not in REPORT_FILE or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
