"""Seal = canonical JSON payload + Ed25519 signature, carried in the QR as SG1.<b64url(payload)>.<b64url(sig)>.

b64url is unpadded. Payload uses short keys (see FIELD_KEYS); the public API uses long keys.
"""
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PREFIX = "SG1"
FIELD_KEYS = {"name": "n", "student_id": "sid", "program": "prog", "award": "aw", "grade": "gr", "date_issued": "dt"}


class SealError(ValueError):
    """Seal text is not a well-formed SG1 seal."""


@dataclass(frozen=True)
class SealData:
    kid: str
    doc_id: str
    version: int
    fields: dict[str, str]  # long keys: name, student_id, program, award, grade, date_issued
    payload: bytes  # exact signed bytes
    signature: bytes


@dataclass(frozen=True)
class SealCheck:
    ok: bool
    reason: str  # "ok" | "malformed" | "untrusted_kid" | "bad_signature"
    data: SealData | None  # parsed payload whenever it parses, even if untrusted


def canonical_json(obj) -> bytes:
    """json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) encoded as UTF-8."""
    raise NotImplementedError


def kid_of(public_key: Ed25519PublicKey) -> str:
    """First 8 hex chars of SHA-256 of the raw 32-byte public key."""
    raise NotImplementedError


def load_or_create_issuer_key(keys_dir: Path | None = None) -> tuple[Ed25519PrivateKey, str]:
    """Load keys_dir/issuer_ed25519.pem (PKCS8 PEM, unencrypted), creating it on first run.

    Always ensures keys_dir/trusted/<kid>.pub exists (hex of the raw public key). Returns (private_key, kid).
    keys_dir defaults to core.KEYS_DIR.
    """
    raise NotImplementedError


def load_trusted_keys(keys_dir: Path | None = None) -> dict[str, Ed25519PublicKey]:
    """Every keys_dir/trusted/*.pub as {kid: public_key}. A file whose name doesn't match kid_of(key) is skipped."""
    raise NotImplementedError


def make_seal(fields: dict[str, str], doc_id: str, version: int, private_key: Ed25519PrivateKey) -> str:
    """Build and sign the seal string. kid is derived from private_key. fields uses long keys (all six required)."""
    raise NotImplementedError


def parse_seal(text: str) -> SealData:
    """Decode without verifying. Raises SealError on any structural problem (prefix, base64, JSON, missing keys)."""
    raise NotImplementedError


def verify_seal(text: str, trusted: dict[str, Ed25519PublicKey]) -> SealCheck:
    """Never raises. malformed -> data None; unknown kid -> untrusted_kid; wrong signature -> bad_signature."""
    raise NotImplementedError
