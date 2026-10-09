import pytest

from core.registry import Registry

F = {"name": "Ana Ñ"}


def test_issue_get_next(tmp_path):
    r = Registry(tmp_path / "r.db")
    assert r.next_version("d1") == 1 and r.get("d1") is None
    r.issue("d1", 1, "kid1", F, "SG1.x.y")
    e = r.get("d1")
    assert e["status"] == "active" and e["fields"] == F and e["current_version"] == 1 and e["issued_at"]
    assert r.next_version("d1") == 2


def test_reissue_supersedes(tmp_path):
    r = Registry(tmp_path / "r.db")
    r.issue("d1", 1, "k", F, "s1")
    r.issue("d1", 2, "k", F, "s2")
    assert r.get("d1", 1)["status"] == "superseded" and r.get("d1", 1)["current_version"] == 2
    assert r.get("d1")["version"] == 2 and r.get("d1")["status"] == "active"


def test_revoke_sticks(tmp_path):
    r = Registry(tmp_path / "r.db")
    assert r.revoke("nope") is False
    r.issue("d1", 1, "k", F, "s1")
    assert r.revoke("d1") is True
    r.issue("d1", 2, "k", F, "s2")
    assert r.get("d1", 1)["status"] == "revoked" and r.get("d1", 2)["status"] == "active"
    r.revoke("d1")
    assert r.get("d1", 2)["status"] == "revoked"


def test_list_order_and_default_path():
    r = Registry()  # default path under SIGNET_DATA_DIR
    r.issue("a", 1, "k", F, "s")
    r.issue("b", 1, "k", F, "s")
    assert [e["doc_id"] for e in r.list()] == ["b", "a"]


def test_duplicate(tmp_path):
    r = Registry(tmp_path / "r.db")
    r.issue("d1", 1, "k", F, "s")
    with pytest.raises(ValueError):
        r.issue("d1", 1, "k", F, "s")
