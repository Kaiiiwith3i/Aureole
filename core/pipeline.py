"""issue() / reissue() / revoke() / verify(). Orchestrator-owned. See CONTRACTS.md."""
from app.schemas import Report


def issue(fields: dict[str, str]) -> dict:
    """Sign, render, save PNG+PDF under data_dir()/issued/, register.
    Returns {"doc_id", "version", "seal", "png_path", "pdf_path"} (paths are pathlib.Path)."""
    raise NotImplementedError


def reissue(doc_id: str, fields: dict[str, str]) -> dict:
    """New version of an existing doc_id; the old one becomes superseded. Same return shape as issue(). KeyError if unknown."""
    raise NotImplementedError


def revoke(doc_id: str) -> bool:
    raise NotImplementedError


def verify(data: bytes, filename: str = "upload") -> Report:
    """Verify PNG/JPG/PDF bytes. Never raises on bad input: unreadable files come back as NO_SEAL/INCONCLUSIVE reports."""
    raise NotImplementedError
