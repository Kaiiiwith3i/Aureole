"""Proves the product works with the network gone: sockets are blocked, then a full issue -> verify cycle runs."""
import re
import socket
from pathlib import Path

import pytest

from tests.test_pipeline import LETTER, png

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise OSError("network access is blocked in this test")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def test_issue_then_verify_without_network(no_network):
    from core import pipeline, stamp

    issued = pipeline.issue(LETTER.encode(), "employment.txt")
    pdf = issued["pdf_path"].read_bytes()
    assert pipeline.verify([("sealed.pdf", pdf)]).mode == "digital"
    report = pipeline.verify([("scan.png", png(stamp.render_page(pdf, 0)))])
    assert report.verdict == "AUTHENTIC", report.headline
    assert report.doc_id == issued["doc_id"]
    assert pipeline.revoke(issued["doc_id"])
    assert pipeline.verify([("sealed.pdf", pdf)]).verdict == "REVOKED"


def test_ui_has_no_external_urls():
    for path in [*WEB.glob("*.html"), *WEB.glob("*.js"), *WEB.glob("*.css")]:
        urls = [u for u in re.findall(r"""(?:https?:)?//[\w.-]+\.[a-z]{2,}[^\s"'<>)]*""", path.read_text(encoding="utf-8"))
                if "www.w3.org" not in u]  # SVG/XML namespace identifiers are never fetched
        assert not urls, f"{path.name}: {urls}"
