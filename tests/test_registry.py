import time

import pytest

from core.registry import Registry


def entry(doc="aabbccdd", ver=1, **kw):
    e = dict(doc_id=doc, version=ver, kid="0123abcd", title="T", source_name="a.txt", source_type="txt", pages=2,
             source_sha256="s" * 64, content_sha256="c" * 64, file_sha256=f"f{doc}{ver}")
    return {**e, **kw}


def test_next_version():
    r = Registry()
    assert r.next_version("aabbccdd") == 1
    r.issue(entry())
    assert r.next_version("aabbccdd") == 2
    assert r.next_version("11111111") == 1


def test_issue_get_roundtrip():
    r = Registry()
    r.issue(entry())
    g = r.get("aabbccdd")
    assert {k: g[k] for k in entry()} == entry()
    assert g["status"] == "active" and g["current_version"] == 1 and g["issued_at"].endswith("+00:00")
    assert r.get("aabbccdd", 1) == g
    assert r.get("aabbccdd", 2) is None and r.get("nope") is None


def test_supersede_on_issue():
    r = Registry()
    r.issue(entry(ver=1))
    r.issue(entry(ver=2))
    assert r.get("aabbccdd", 1)["status"] == "superseded"
    assert r.get("aabbccdd", 2)["status"] == "active"
    assert r.get("aabbccdd", 1)["current_version"] == 2
    assert r.get("aabbccdd")["version"] == 2
    r.issue(entry(doc="11111111"))  # other doc untouched
    assert r.get("11111111")["status"] == "active"


def test_supersede_leaves_revoked():
    r = Registry()
    r.issue(entry(ver=1))
    r.revoke("aabbccdd")
    r.issue(entry(ver=2))
    assert r.get("aabbccdd", 1)["status"] == "revoked"


def test_duplicate_version():
    r = Registry()
    r.issue(entry())
    with pytest.raises(ValueError):
        r.issue(entry(file_sha256="other"))
    assert len(r.list()) == 1


def test_missing_key():
    e = entry()
    del e["title"]
    with pytest.raises(KeyError):
        Registry().issue(e)


def test_find_file():
    r = Registry()
    r.issue(entry(ver=1))
    r.issue(entry(ver=2))
    hit = r.find_file("faabbccdd1")
    assert hit == r.get("aabbccdd", 1) and hit["status"] == "superseded" and hit["current_version"] == 2
    assert r.find_file("missing") is None


def test_revoke():
    r = Registry()
    assert r.revoke("zzzzzzzz") is False
    r.issue(entry())
    assert r.revoke("aabbccdd") is True
    assert r.get("aabbccdd")["status"] == "revoked"
    assert r.revoke("aabbccdd") is True  # known doc, idempotent


def test_list_newest_first():
    r = Registry()
    assert r.list() == []
    r.issue(entry(doc="11111111"))
    time.sleep(0.01)
    r.issue(entry(doc="22222222"))
    time.sleep(0.01)
    r.issue(entry(doc="11111111", ver=2))
    assert [(e["doc_id"], e["version"]) for e in r.list()] == [("11111111", 2), ("22222222", 1), ("11111111", 1)]


def test_persists_across_instances(tmp_path):
    db = tmp_path / "x.db"
    Registry(db).issue(entry())
    assert Registry(db).get("aabbccdd")["title"] == "T"
