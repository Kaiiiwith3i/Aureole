import io
import zipfile

import pypdfium2 as pdfium
import pytest

from core import convert, layout


def _text(pdf: bytes) -> str:
    doc = pdfium.PdfDocument(pdf)
    return "\n".join(p.get_textpage().get_text_range() for p in doc)


def _zip(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


DOCX = _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": "<w:document/>"})
XLSX = _zip({"[Content_Types].xml": "<Types/>", "xl/workbook.xml": "<workbook/>"})
XLS = bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 600


def _blank_pdf(pages=1) -> bytes:
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(595, 842)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def test_txt_to_selectable_pdf():
    pdf, kind = convert.to_pdf(b"Hello Signet world\nSecond line\n", "note.txt")
    assert kind == "txt" and pdf.startswith(b"%PDF-")
    t = _text(pdf)
    assert "Hello Signet world" in t and "Second line" in t


def test_txt_accents_and_tabs():
    pdf, _ = convert.to_pdf("Peñaflor, Zoë\tdone".encode(), "a.txt")
    assert "Peñaflor, Zoë" in _text(pdf)


def test_txt_missing_glyph_does_not_crash():
    pdf, _ = convert.to_pdf("abc \U0001F600 日本 def".encode(), "a.txt")
    assert "abc" in _text(pdf) and "def" in _text(pdf)


def test_txt_paginates():
    pdf, _ = convert.to_pdf(("lorem ipsum dolor sit amet " * 6 + "\n").encode() * 120, "long.txt")
    n = len(pdfium.PdfDocument(pdf))
    assert 2 <= n <= layout.MAX_PAGES


def test_txt_wraps_long_line():
    pdf, _ = convert.to_pdf(("word " * 200).encode(), "w.txt")
    lines = _text(pdf).splitlines()
    assert len(lines) > 3 and max(len(x) for x in lines) < 120


def test_txt_too_many_pages():
    with pytest.raises(ValueError, match="pages"):
        convert.to_pdf(b"line\n" * 2000, "big.txt")


def test_txt_empty_and_bad():
    for data in (b"", b"  \n\n ", ):
        with pytest.raises(ValueError):
            convert.to_pdf(data, "a.txt")
    with pytest.raises(ValueError):
        convert.to_pdf(b"\xff\xfe\x00bad", "a.txt")


def test_pdf_passthrough():
    pdf = _blank_pdf(2)
    out, kind = convert.to_pdf(pdf, "x.pdf")
    assert out == pdf and kind == "pdf"


def test_pdf_too_many_pages():
    with pytest.raises(ValueError, match="pages"):
        convert.to_pdf(_blank_pdf(layout.MAX_PAGES + 1), "x.pdf")


def test_pdf_empty_document():
    # a PDF with zero pages: pdfium refuses to open it
    d = pdfium.PdfDocument.new()
    b = io.BytesIO()
    d.save(b)
    with pytest.raises(ValueError, match="damaged|empty"):
        convert.to_pdf(b.getvalue(), "x.pdf")


def test_pdf_password_protected():
    # Minimal RC4-40 encrypted PDF is awkward to build; pdfium reports a password error on open, simulate that.
    from unittest import mock
    err = pdfium.PdfiumError("Failed to load document (PDFium: Incorrect password error).")
    with mock.patch("pypdfium2.PdfDocument", side_effect=err):
        with pytest.raises(ValueError, match="password"):
            convert._check_pdf(b"%PDF-1.4")


def test_garbage_pdf():
    with pytest.raises(ValueError):
        convert.to_pdf(b"%PDF-1.4 not really", "x.pdf")


def test_unsupported_and_mismatch():
    with pytest.raises(ValueError, match="Unsupported"):
        convert.to_pdf(b"\x89PNG\r\n\x1a\n" + b"\0" * 50, "x.txt")
    with pytest.raises(ValueError, match="Unsupported"):
        convert.to_pdf(b"plain text", "x.csv")
    with pytest.raises(ValueError, match="name ends"):
        convert.to_pdf(_blank_pdf(), "x.docx")
    with pytest.raises(ValueError):
        convert.to_pdf(b"", "x.txt")


def test_macro_rejected():
    z = _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": "<w/>", "word/vbaProject.bin": "x"})
    with pytest.raises(ValueError, match="[Mm]acro"):
        convert.to_pdf(z, "m.docx")


def test_office_needs_libreoffice(monkeypatch):
    monkeypatch.setattr(convert, "_soffice", lambda: None)
    assert not convert.has_converter()
    for data, name in ((DOCX, "a.docx"), (XLSX, "a.xlsx"), (XLS, "a.xls")):
        with pytest.raises(ValueError, match="LibreOffice"):
            convert.to_pdf(data, name)


def _fake_soffice(tmp_path, monkeypatch, pdf: bytes):
    (tmp_path / "fake.pdf").write_bytes(pdf)
    exe = tmp_path / "soffice"
    exe.write_text('#!/bin/sh\nfor a; do last=$a; done\ncp "' + str(tmp_path / "fake.pdf") + '" "${last%.*}.pdf"\n')
    exe.chmod(0o755)
    monkeypatch.setenv("SIGNET_SOFFICE", str(exe))


@pytest.mark.parametrize("data,name,kind", [(DOCX, "a.docx", "docx"), (XLSX, "a.xlsx", "xlsx"), (XLS, "a.xls", "xls")])
def test_office_with_fake_converter(tmp_path, monkeypatch, data, name, kind):
    pdf = _blank_pdf(2)
    _fake_soffice(tmp_path, monkeypatch, pdf)
    assert convert.has_converter()
    out, k = convert.to_pdf(data, name)
    assert k == kind and out == pdf


def test_converter_failure(tmp_path, monkeypatch):
    exe = tmp_path / "soffice"
    exe.write_text("#!/bin/sh\nexit 1\n")
    exe.chmod(0o755)
    monkeypatch.setenv("SIGNET_SOFFICE", str(exe))
    with pytest.raises(ValueError, match="could not be converted"):
        convert.to_pdf(DOCX, "a.docx")


def test_converter_output_over_page_limit(tmp_path, monkeypatch):
    _fake_soffice(tmp_path, monkeypatch, _blank_pdf(layout.MAX_PAGES + 1))
    with pytest.raises(ValueError, match="pages"):
        convert.to_pdf(DOCX, "a.docx")


def test_xls_ole2_wrong_extension():
    with pytest.raises(ValueError):
        convert.to_pdf(XLS, "a.doc")
