"""Upload -> content PDF. Type is decided by the bytes, never by the extension alone. Builder B."""
import ctypes
import os
import shutil
import subprocess
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import ImageFont

from core import FONTS_DIR, layout, log

SOURCE_TYPES = ("txt", "docx", "pdf", "xls", "xlsx")
_OLE2 = bytes.fromhex("D0CF11E0A1B11AE1")
_SOFFICE_FALLBACKS = ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
                      r"C:\Program Files\LibreOffice\program\soffice.exe")
_PAGE_W, _PAGE_H, _MARGIN, _SIZE, _LEAD = 595.0, 842.0, 56.0, 11.0, 14.5  # A4 in pt


def _soffice() -> str | None:
    env = os.environ.get("SIGNET_SOFFICE")
    if env and Path(env).exists():
        return env
    return shutil.which("soffice") or next((p for p in _SOFFICE_FALLBACKS if Path(p).exists()), None)


def has_converter() -> bool:
    """True when LibreOffice (`soffice`) is available. Lookup order: env SIGNET_SOFFICE, PATH,
    /Applications/LibreOffice.app/Contents/MacOS/soffice, C:\\Program Files\\LibreOffice\\program\\soffice.exe."""
    return _soffice() is not None


def _check_pdf(pdf: bytes) -> None:
    try:
        doc = pdfium.PdfDocument(pdf)
        n = len(doc)
        doc.close()
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise ValueError("This PDF is password-protected. Remove the password and upload it again.")
        raise ValueError("This PDF could not be opened; it may be damaged.")
    if n == 0:
        raise ValueError("This document is empty.")
    if n > layout.MAX_PAGES:
        raise ValueError(f"This document has {n} pages; the limit is {layout.MAX_PAGES}.")


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Greedy word wrap; a word wider than the line is split by characters."""
    out = []
    for para in text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").split("\n"):
        line = ""
        for word in para.split(" "):
            cand = f"{line} {word}" if line else word
            if font.getlength(cand) <= width:
                line = cand
                continue
            if line:
                out.append(line)
            line = ""
            for ch in word:
                if line and font.getlength(line + ch) > width:
                    out.append(line)
                    line = ""
                line += ch
        out.append(line)
    return out


def _txt_to_pdf(text: str) -> bytes:
    text = "".join(c for c in text if c in "\n\r\t" or c >= " " and c != "\x7f")
    if not text.strip():
        raise ValueError("This document is empty.")
    ttf = (FONTS_DIR / "DejaVuSans.ttf").read_bytes()
    # measure at 10x for precision; widths scale linearly
    font = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), int(_SIZE * 10))
    lines = _wrap(text, font, (_PAGE_W - 2 * _MARGIN) * 10)
    per_page = int((_PAGE_H - 2 * _MARGIN) // _LEAD)
    pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
    if len(pages) > layout.MAX_PAGES:
        raise ValueError(f"This document has {len(pages)} pages; the limit is {layout.MAX_PAGES}.")
    doc = pdfium.PdfDocument.new()
    buf = (ctypes.c_uint8 * len(ttf)).from_buffer_copy(ttf)
    fnt = raw.FPDFText_LoadFont(doc.raw, buf, len(ttf), raw.FPDF_FONT_TRUETYPE, 1)  # cid=1: Identity-H, full Unicode
    for chunk in pages:
        page = doc.new_page(_PAGE_W, _PAGE_H)
        for i, ln in enumerate(chunk):
            if not ln.strip():
                continue
            obj = raw.FPDFPageObj_CreateTextObj(doc.raw, fnt, _SIZE)
            wide = (ln + "\0").encode("utf-16-le")
            raw.FPDFText_SetText(obj, ctypes.cast(ctypes.create_string_buffer(wide, len(wide)), ctypes.POINTER(ctypes.c_ushort)))
            raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, _MARGIN, _PAGE_H - _MARGIN - _SIZE - i * _LEAD)
            raw.FPDFPage_InsertObject(page.raw, obj)
        page.gen_content()
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def _office_to_pdf(data: bytes, ext: str) -> bytes:
    exe = _soffice()
    if not exe:
        raise ValueError("Converting Word and Excel files needs LibreOffice, which isn't installed on this "
                         "machine. Install LibreOffice, or upload a PDF or TXT file instead.")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"upload.{ext}"
        src.write_bytes(data)
        profile = Path(tmp) / "profile"
        cmd = [exe, "--headless", f"-env:UserInstallation={profile.as_uri()}", "--convert-to", "pdf",
               "--outdir", tmp, str(src)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        except subprocess.TimeoutExpired:
            raise ValueError("Converting this document took too long and was stopped.")
        except (subprocess.CalledProcessError, OSError) as e:
            log.warning("soffice failed: %s", e)
            raise ValueError("This document could not be converted to PDF.")
        out = Path(tmp) / "upload.pdf"
        if not out.exists():
            raise ValueError("This document could not be converted to PDF.")
        return out.read_bytes()


def to_pdf(data: bytes, filename: str) -> tuple[bytes, str]:
    """(content PDF bytes, source_type) for a TXT, DOCX, PDF, XLS or XLSX upload.

    - pdf (`%PDF-`): returned as is after checking it opens without a password.
    - txt (decodes as UTF-8, no NUL bytes, extension .txt): laid out by us on A4 portrait with real PDF text objects
      (pdfium, assets/fonts/DejaVuSans.ttf, 11 pt, word-wrapped, paginated), so the text stays selectable. No LibreOffice.
    - docx / xlsx (zip with word/ or xl/) and xls (OLE2 magic): `soffice --headless --convert-to pdf` in a temp dir with
      its own profile dir (-env:UserInstallation), 120 s timeout. No shell.
    Raises ValueError with a sentence the UI can show for: unsupported or mismatched type, empty document,
    password-protected file, macro-enabled OOXML (contains vbaProject.bin), more than layout.MAX_PAGES pages,
    DOCX/XLS/XLSX when has_converter() is False, a failed or timed-out conversion.
    """
    if not data:
        raise ValueError("This file is empty.")
    ext = Path(filename).suffix.lower().lstrip(".")
    unsupported = ValueError("Unsupported file. Upload a TXT, DOCX, PDF, XLS or XLSX file.")
    if data.startswith(b"%PDF-"):
        kind = "pdf"
    elif data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            raise unsupported
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise ValueError("Macro-enabled documents are not accepted. Save a copy without macros and upload that.")
        kind = "docx" if any(n.startswith("word/") for n in names) else "xlsx" if any(n.startswith("xl/") for n in names) else None
        if kind is None:
            raise unsupported
    elif data.startswith(_OLE2):
        if ext == "xls":
            kind = "xls"
        elif ext in ("docx", "xlsx"):
            raise ValueError("This file looks password-protected or is in an old format. Save it as an unprotected "
                             "DOCX or XLSX and upload it again.")
        else:
            raise unsupported
    elif ext == "txt" and b"\0" not in data:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("This text file isn't UTF-8. Save it as UTF-8 and upload it again.")
        return _txt_to_pdf(text), "txt"
    else:
        raise unsupported
    if ext != kind:
        raise ValueError(f"The file contents are {kind.upper()} but the name ends in .{ext or '(none)'}. Rename it or upload the right file.")
    pdf = data if kind == "pdf" else _office_to_pdf(data, kind)
    _check_pdf(pdf)
    return pdf, kind
