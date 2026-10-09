"""Pydantic models = the API contract. Mirrors CONTRACTS.md."""
from typing import Literal

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

Verdict = Literal["AUTHENTIC", "AUTHENTIC_WITH_NOTES", "MISMATCH", "INCONCLUSIVE", "REVOKED", "INVALID_SEAL", "NO_SEAL"]
FieldStatus = Literal["MATCH", "MISMATCH", "UNREADABLE"]
FindingType = Literal["stamp", "handwriting", "physical_damage", "fold", "text_change", "digital_edit", "unknown"]
Severity = Literal["info", "warning", "critical"]
RegistryStatus = Literal["active", "revoked", "superseded", "unknown"]


class CertFields(BaseModel):
    # Length caps keep the seal within QR version 20 (see CONTRACTS.md).
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)
    student_id: str = Field(min_length=1, max_length=20)
    program: str = Field(min_length=1, max_length=60)
    award: str = Field(min_length=1, max_length=40)
    grade: str = Field(min_length=1, max_length=8)
    date_issued: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("date_issued")
    @classmethod
    def _real_date(cls, v: str) -> str:
        date.fromisoformat(v)  # ValueError for 2026-13-45
        return v


class IssueResponse(BaseModel):
    doc_id: str
    version: int
    png_url: str
    pdf_url: str


class FieldResult(BaseModel):
    key: str
    label: str
    signed: str
    read: str
    status: FieldStatus
    similarity: float
    confidence: float


class Finding(BaseModel):
    id: str
    type: FindingType
    bbox: list[int]  # [x, y, w, h] in Report.image_size pixel space
    field: str | None = None
    severity: Severity
    confidence: float
    message: str


class ReportImages(BaseModel):
    scan: str | None = None
    expected: str | None = None
    diff: str | None = None
    ela: str | None = None


class Report(BaseModel):
    report_id: str
    filename: str = ""
    verdict: Verdict
    headline: str
    doc_id: str | None = None
    version: int | None = None
    current_version: int | None = None  # set when REVOKED by supersession
    kid: str | None = None
    registry_status: RegistryStatus | None = None
    fields: list[FieldResult] = []
    findings: list[Finding] = []
    notes: list[str] = []
    timings: dict[str, float] = {}  # stage -> ms, plus "total"
    images: ReportImages = ReportImages()
    image_size: list[int] = [2339, 1654]  # [w, h] coordinate space of finding bboxes and images


class RegistryEntry(BaseModel):
    doc_id: str
    version: int
    kid: str
    fields: CertFields
    status: RegistryStatus
    issued_at: str
    current_version: int
    png_url: str
    pdf_url: str


class Health(BaseModel):
    ok: bool
    ocr_engine: str
    offline: bool = True
