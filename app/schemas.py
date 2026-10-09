"""Pydantic models = the API contract. Mirrors CONTRACTS.md."""
from typing import Literal

from pydantic import BaseModel

Verdict = Literal["AUTHENTIC", "AUTHENTIC_WITH_NOTES", "MODIFIED", "INCONCLUSIVE", "REVOKED", "INVALID_SEAL", "NOT_ISSUED"]
LineStatus = Literal["MATCH", "MISMATCH", "UNREADABLE"]
FindingType = Literal["stamp", "handwriting", "physical_damage", "fold", "text_change", "unknown"]
Severity = Literal["info", "warning", "critical"]
RegistryStatus = Literal["active", "revoked", "superseded"]
SourceType = Literal["txt", "docx", "pdf", "xls", "xlsx"]


class Login(BaseModel):
    password: str


class IssueResponse(BaseModel):
    doc_id: str
    version: int
    title: str
    pages: int
    fingerprint: str  # 16 hex chars, as printed in the page footer
    pdf_url: str


class LineResult(BaseModel):
    """A line that did NOT read back as MATCH (matching lines are only counted)."""
    index: int  # position in the page's lines
    bbox: list[int]
    expected: str | None  # the issued text; null for non-staff
    read: str
    status: LineStatus
    similarity: float
    confidence: float


class Finding(BaseModel):
    id: str
    type: FindingType
    bbox: list[int]  # [x, y, w, h] in PageReport.image_size pixel space
    line: int | None = None
    severity: Severity
    confidence: float
    message: str


class ReportImages(BaseModel):
    scan: str | None = None
    expected: str | None = None  # null for non-staff
    diff: str | None = None
    ela: str | None = None


class PageReport(BaseModel):
    index: int  # 1-based position in the upload
    page: int | None = None  # page number from the seal
    verdict: Verdict
    headline: str
    lines: list[LineResult] = []
    lines_total: int = 0
    lines_matched: int = 0
    lines_unchecked: int = 0  # not machine-readable at issue time, or beyond the per-page cap
    findings: list[Finding] = []
    notes: list[str] = []
    images: ReportImages = ReportImages()
    image_size: list[int] = [1654, 2339]  # [w, h] coordinate space of bboxes and images


class Report(BaseModel):
    report_id: str
    filename: str = ""
    mode: Literal["digital", "pages"]
    verdict: Verdict
    headline: str
    doc_id: str | None = None
    version: int | None = None
    current_version: int | None = None  # set when REVOKED by supersession
    kid: str | None = None
    registry_status: RegistryStatus | None = None
    pages_total: int | None = None  # page count of the issued document
    pages_checked: list[int] = []  # issued page numbers that were provided and analysed
    pages: list[PageReport] = []  # empty in digital mode
    notes: list[str] = []
    timings: dict[str, float] = {}  # stage -> ms, plus "total"


class RegistryEntry(BaseModel):
    doc_id: str
    version: int
    kid: str
    title: str
    source_name: str
    source_type: SourceType
    pages: int
    fingerprint: str
    status: RegistryStatus
    issued_at: str
    current_version: int
    pdf_url: str


class Health(BaseModel):
    ok: bool
    ocr_engine: str
    converter: bool  # LibreOffice found, so DOCX/XLS can be issued
    offline: bool = True
