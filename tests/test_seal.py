import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core import seal as S

FP = "0123456789abcdef"
B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def trusted(key):
    return {S.kid_of(key.public_key()): key.public_key()}


@pytest.fixture
def text(key):
    return S.make_seal("aabbccdd", 3, 2, 5, FP, key)


def test_round_trip(text, trusted, key):
    assert len(text) <= 140
    c = S.verify_seal(text, trusted)
    assert c.ok and c.reason == "ok"
    d = c.data
    assert (d.doc_id, d.version, d.page, d.pages, d.fingerprint) == ("aabbccdd", 3, 2, 5, FP)
    assert d.kid == S.kid_of(key.public_key())


def test_every_signed_char_change_rejected(text, trusted):
    body = text.rsplit(".", 1)[0]
    for i, ch in enumerate(body):
        if ch == ".":
            continue
        bad = "0" if ch != "0" else "1"
        c = S.verify_seal(body[:i] + bad + body[i + 1:] + "." + text.rsplit(".", 1)[1], trusted)
        assert not c.ok and c.reason in ("bad_signature", "malformed", "untrusted_kid"), (i, c)


def test_every_signature_char_change_rejected(text, trusted):
    head, sig = text.rsplit(".", 1)
    for i, ch in enumerate(sig):
        bad = "A" if ch != "A" else "B"
        c = S.verify_seal(f"{head}.{sig[:i]}{bad}{sig[i + 1:]}", trusted)
        assert not c.ok and c.reason in ("bad_signature", "malformed"), i


def test_unknown_kid(text):
    c = S.verify_seal(text, {})
    assert not c.ok and c.reason == "untrusted_kid" and c.data.doc_id == "aabbccdd"


def test_wrong_key_bad_signature(text):
    other = Ed25519PrivateKey.generate()
    kid = S.verify_seal(text, {}).data.kid
    c = S.verify_seal(text, {kid: other.public_key()})
    assert not c.ok and c.reason == "bad_signature" and c.data is not None


def _parts(text):
    return text.split(".")


def test_malformed(text, trusted):
    p = _parts(text)
    cases = {
        "prefix": ".".join(["SG1"] + p[1:]),
        "missing part": ".".join(p[:3] + p[4:]),
        "extra part": text + ".x",
        "leading zero ver": ".".join(p[:2] + ["03"] + p[3:]),
        "zero ver": ".".join(p[:2] + ["0"] + p[3:]),
        "page > pages": ".".join(p[:3] + ["6", "5"] + p[5:]),
        "non-hex doc": ".".join([p[0], "gabbccdd"] + p[2:]),
        "upper-hex doc": ".".join([p[0], "AABBCCDD"] + p[2:]),
        "short doc": ".".join([p[0], "aabbcc"] + p[2:]),
        "short sig": text[:-1],
        "long sig": text + "A",
        "bad sig char": text[:-1] + "+",
        "empty": "",
        "garbage": "hello world",
        "unicode": text[:-1] + "é",
    }
    for name, bad in cases.items():
        c = S.verify_seal(bad, trusted)
        assert not c.ok and c.reason == "malformed" and c.data is None, name


def test_non_canonical_base64(text, trusted):
    head, sig = text.rsplit(".", 1)
    last = B64.index(sig[-1])
    assert last % 16 == 0  # 64-byte signature: last char's low 4 bits are padding
    bad = f"{head}.{sig[:-1]}{B64[last + 1]}"
    c = S.verify_seal(bad, trusted)
    assert not c.ok and c.reason == "malformed"


@pytest.mark.parametrize("args", [
    ("aabbccdd", 1, 6, 5, FP),      # page > pages
    ("aabbccdd", 1, 0, 5, FP),      # page 0
    ("aabbccdd", 0, 1, 5, FP),      # version 0
    ("gabbccdd", 1, 1, 5, FP),      # non-hex doc
    ("aabbcc", 1, 1, 5, FP),        # short doc
    ("aabbccdd", 1, 1, 5, "xyz"),   # bad fingerprint
])
def test_make_seal_refuses(args, key):
    with pytest.raises(ValueError):
        S.make_seal(*args, key)
    assert issubclass(S.SealError, ValueError)


def test_issuer_key_created_and_stable(tmp_path):
    k1, kid1 = S.load_or_create_issuer_key(tmp_path)
    assert (tmp_path / "issuer_ed25519.pem").exists()
    assert (tmp_path / "trusted" / f"{kid1}.pub").exists()
    k2, kid2 = S.load_or_create_issuer_key(tmp_path)
    assert kid1 == kid2 and k1.private_bytes_raw() == k2.private_bytes_raw()
    assert kid1 in S.load_trusted_keys(tmp_path)


def test_trusted_skips_mismatched_name(tmp_path):
    _, kid = S.load_or_create_issuer_key(tmp_path)
    other = Ed25519PrivateKey.generate().public_key()
    raw = other.public_bytes_raw().hex()
    (tmp_path / "trusted" / "deadbeef.pub").write_text(raw)
    (tmp_path / "trusted" / "notakey.pub").write_text("zz")
    assert set(S.load_trusted_keys(tmp_path)) == {kid}


def test_sign_verify_with_loaded_key(tmp_path):
    k, kid = S.load_or_create_issuer_key(tmp_path)
    t = S.make_seal("00000001", 1, 1, 1, FP, k)
    assert S.verify_seal(t, S.load_trusted_keys(tmp_path)).ok
