"""Seal = canonical JSON payload + Ed25519 signature, carried in the QR as SG1.<b64url(payload)>.<b64url(sig)>.

b64url is unpadded. Payload uses short keys (see FIELD_KEYS); the public API uses long keys.
"""
import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from core import KEYS_DIR

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
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


_RAW = serialization.Encoding.Raw, serialization.PublicFormat.Raw


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    b = base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_", validate=True)
    if _b64e(b) != s:  # reject non-canonical trailing bits so every text change changes the bytes
        raise ValueError("non-canonical base64")
    return b


def canonical_json(obj) -> bytes:
    """json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) encoded as UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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


def make_seal(fields: dict[str, str], doc_id: str, version: int, private_key: Ed25519PrivateKey) -> str:
    """Build and sign the seal string. kid is derived from private_key. fields uses long keys (all six required)."""
    payload = canonical_json({"kid": kid_of(private_key.public_key()), "doc": doc_id, "ver": version,
                              "f": {short: fields[long] for long, short in FIELD_KEYS.items()}})
    return f"{PREFIX}.{_b64e(payload)}.{_b64e(private_key.sign(payload))}"


def parse_seal(text: str) -> SealData:
    """Decode without verifying. Raises SealError on any structural problem (prefix, base64, JSON, missing keys)."""
    try:
        prefix, p, s = text.strip().split(".")
        if prefix != PREFIX:
            raise ValueError("prefix")
        payload, sig = _b64d(p), _b64d(s)
        obj = json.loads(payload.decode("utf-8"))
        kid, doc, ver, f = obj["kid"], obj["doc"], obj["ver"], obj["f"]
        if not (isinstance(kid, str) and isinstance(doc, str) and type(ver) is int and isinstance(f, dict)):
            raise ValueError("types")
        if not all(isinstance(f[k], str) for k in FIELD_KEYS.values()):
            raise ValueError("fields")
        fields = {long: f[short] for long, short in FIELD_KEYS.items()}
    except (ValueError, KeyError, TypeError, AttributeError) as e:  # UnicodeDecodeError/JSONDecodeError/binascii.Error are ValueErrors
        raise SealError(f"malformed seal: {e}") from e
    return SealData(kid, doc, ver, fields, payload, sig)


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
        key.verify(d.signature, d.payload)
    except InvalidSignature:
        return SealCheck(False, "bad_signature", d)
    return SealCheck(True, "ok", d)
