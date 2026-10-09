"""Frame every page of a content PDF with markers, the signed QR seal and the footer; render pages. Builder B."""
import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def fingerprint(content_pdf: bytes) -> str:
    """First 16 hex chars of SHA-256 of the content PDF."""
    raise NotImplementedError


def page_count(pdf: bytes) -> int:
    raise NotImplementedError


def stamp(content_pdf: bytes, doc_id: str, version: int, private_key: Ed25519PrivateKey, issued_on: str) -> bytes:
    """The issued PDF. Every output page is A4 (portrait or landscape, following the source page), laid out by
    core.layout: the source page embedded as a form XObject (vector, text stays selectable) fitted into layout.content,
    the four ArUco markers, the QR of seal.make_seal(doc_id, version, p, n, fingerprint(content_pdf), private_key)
    rendered with qr.render_qr, and the footer text inside layout.footer:
        Signet document <doc_id> v<version> - page <p> of <n>
        Fingerprint <h in groups of 4>
        Issued <issued_on>. Verify this page with the issuing office.
    Markers, QR and footer are drawn in black on white. issued_on is YYYY-MM-DD."""
    raise NotImplementedError


def render_page(pdf: bytes, index: int) -> np.ndarray:
    """BGR render of page `index` (0-based) at 200 DPI. For an issued PDF the result is exactly layout(...).size
    (resize by a pixel if rounding differs)."""
    raise NotImplementedError
