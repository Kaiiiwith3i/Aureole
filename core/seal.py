"""Seal = SG2.<doc>.<ver>.<p>.<n>.<h>.<kid>.<sig>, carried in the QR of every issued page. See CONTRACTS.md.

sig = unpadded base64url Ed25519 signature over the UTF-8 bytes of everything before the last dot.
"""
import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from core import KEYS_DIR

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PREFIX = "SG2"
_SEAL = re.compile(r"SG2\.([0-9a-f]{8})\.([1-9]\d{0,3})\.([1-9]\d{0,3})\.([1-9]\d{0,3})\.([0-9a-f]{16})\.([0-9a-f]{8})\.([A-Za-z0-9_-]{86})")


class SealError(ValueError):
    """Seal text is not a well-formed SG2 seal."""


@dataclass(frozen=True)
class SealData:
    kid: str
    doc_id: str
    version: int
    page: int  # 1-based
    pages: int
    fingerprint: str  # first 16 hex chars of SHA-256 of the content PDF
    signed: bytes  # exact signed bytes
    signature: bytes


@dataclass(frozen=True)
class SealCheck:
    ok: bool
    reason: str  # "ok" | "malformed" | "untrusted_kid" | "bad_signature"
    data: SealData | None  # parsed seal whenever it parses, even if untrusted


_RAW = serialization.Encoding.Raw, serialization.PublicFormat.Raw


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    b = base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_", validate=True)
    if _b64e(b) != s:  # reject non-canonical trailing bits so every text change changes the bytes
        raise ValueError("non-canonical base64")
    return b


def _raw(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(*_RAW)


def kid_of(public_key: Ed25519PublicKey) -> str:
    """First 8 hex chars of SHA-256 of the raw 32-byte public key."""
    return hashlib.sha256(_raw(public_key)).hexdigest()[:8]


def load_or_create_issuer_key(keys_dir: Path | None = None) -> tuple[Ed25519PrivateKey, str]:
    """Load keys_dir/issuer_ed25519.pem (PKCS8 PEM, unencrypted), creating it on first run.

    Always ensures keys_dir/trusted/<kid>.pub exists (hex of the raw public key). Returns (private_key, kid).
    keys_dir defaults to core.KEYS_DIR.
    """
    keys_dir = Path(keys_dir or KEYS_DIR)
    pem = keys_dir / "issuer_ed25519.pem"
    if pem.exists():
        key = serialization.load_pem_private_key(pem.read_bytes(), password=None)
    else:
        key = Ed25519PrivateKey.generate()
        keys_dir.mkdir(parents=True, exist_ok=True)
        pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        pem.chmod(0o600)
    kid = kid_of(key.public_key())
    pub = keys_dir / "trusted" / f"{kid}.pub"
    pub.parent.mkdir(parents=True, exist_ok=True)
    pub.write_text(_raw(key.public_key()).hex())
    return key, kid


def load_trusted_keys(keys_dir: Path | None = None) -> dict[str, Ed25519PublicKey]:
    """Every keys_dir/trusted/*.pub as {kid: public_key}. A file whose name doesn't match kid_of(key) is skipped."""
    out = {}
    for f in (Path(keys_dir or KEYS_DIR) / "trusted").glob("*.pub"):
        try:
            key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(f.read_text().strip()))
        except ValueError:
            continue
        if kid_of(key) == f.stem:
            out[f.stem] = key
    return out


def make_seal(doc_id: str, version: int, page: int, pages: int, fingerprint: str, private_key: Ed25519PrivateKey) -> str:
    """Build and sign the seal string for one page. kid is derived from private_key."""
    body = f"{PREFIX}.{doc_id}.{version}.{page}.{pages}.{fingerprint}.{kid_of(private_key.public_key())}"
    text = f"{body}.{_b64e(private_key.sign(body.encode()))}"
    parse_seal(text)  # refuse to sign anything the verifier would call malformed
    return text


def parse_seal(text: str) -> SealData:
    """Decode without verifying. Raises SealError on any structural problem."""
    m = _SEAL.fullmatch(text.strip())
    if not m:
        raise SealError("malformed seal")
    doc, ver, page, pages, h, kid, sig = m.groups()
    try:
        signature = _b64d(sig)
    except ValueError as e:
        raise SealError(f"malformed seal: {e}") from e
    if int(page) > int(pages):
        raise SealError("malformed seal: page beyond page count")
    return SealData(kid, doc, int(ver), int(page), int(pages), h, text.strip().rsplit(".", 1)[0].encode(), signature)


def verify_seal(text: str, trusted: dict[str, Ed25519PublicKey]) -> SealCheck:
    """Never raises. malformed -> data None; unknown kid -> untrusted_kid; wrong signature -> bad_signature."""
    try:
        d = parse_seal(text)
    except SealError:
        return SealCheck(False, "malformed", None)
    key = trusted.get(d.kid)
    if key is None:
        return SealCheck(False, "untrusted_kid", d)
    try:
        key.verify(d.signature, d.signed)
    except InvalidSignature:
        return SealCheck(False, "bad_signature", d)
    return SealCheck(True, "ok", d)
