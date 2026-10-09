import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.seal import (canonical_json, kid_of, load_or_create_issuer_key, load_trusted_keys, make_seal, parse_seal,
                       verify_seal)

FIELDS = {"name": "Juan Dela Cruz", "student_id": "2021-00123", "program": "BS Computer Science",
          "award": "Cum Laude", "grade": "1.45", "date_issued": "2026-03-15"}


@pytest.fixture
def key(tmp_path):
    k, kid = load_or_create_issuer_key(tmp_path)
    return k, kid, load_trusted_keys(tmp_path)


def test_round_trip(key):
    k, kid, trusted = key
    chk = verify_seal(make_seal(FIELDS, "ab12cd34", 2, k), trusted)
    assert chk.ok and chk.reason == "ok"
    assert chk.data.fields == FIELDS and chk.data.kid == kid and chk.data.doc_id == "ab12cd34" and chk.data.version == 2


def test_any_single_byte_flip_fails(key):
    k, _, trusted = key
    seal = make_seal(FIELDS, "ab12cd34", 1, k)
    start = len("SG1.")
    for i in range(start, len(seal)):
        if seal[i] == ".":
            continue
        bad = seal[:i] + ("B" if seal[i] != "B" else "C") + seal[i + 1:]
        assert verify_seal(bad, trusted).reason in ("bad_signature", "malformed", "untrusted_kid"), i
        assert not verify_seal(bad, trusted).ok


def test_untrusted_kid(key):
    _, _, trusted = key
    other = Ed25519PrivateKey.generate()
    chk = verify_seal(make_seal(FIELDS, "ab12cd34", 1, other), trusted)
    assert not chk.ok and chk.reason == "untrusted_kid" and chk.data.fields == FIELDS


@pytest.mark.parametrize("text", ["", "garbage", "SG1.a.b", "SG2.e30.AA", "SG1.!!!.???", "SG1.e30.AA"])
def test_malformed(key, text):
    chk = verify_seal(text, key[2])
    assert chk.reason == "malformed" and chk.data is None


def test_parse_rejects_wrong_types(key):
    from core.seal import _b64e
    p = canonical_json({"kid": "x", "doc": "d", "ver": "1", "f": {}})
    with pytest.raises(ValueError):
        parse_seal(f"SG1.{_b64e(p)}.{_b64e(b'sig')}")


def test_canonical_json():
    assert canonical_json({"b": 1, "a": "ñ"}) == canonical_json({"a": "ñ", "b": 1}) == '{"a":"ñ","b":1}'.encode()


def test_key_idempotent(tmp_path):
    k1, kid1 = load_or_create_issuer_key(tmp_path)
    k2, kid2 = load_or_create_issuer_key(tmp_path)
    assert kid1 == kid2 == kid_of(k1.public_key()) and len(kid1) == 8
    int(kid1, 16)
    assert (tmp_path / "trusted" / f"{kid1}.pub").exists()
    assert kid1 in load_trusted_keys(tmp_path)
