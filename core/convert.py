"""Upload -> content PDF. Type is decided by the bytes, never by the extension alone. Builder B."""

SOURCE_TYPES = ("txt", "docx", "pdf", "xls", "xlsx")


def has_converter() -> bool:
    """True when LibreOffice (`soffice`) is available. Lookup order: env SIGNET_SOFFICE, PATH,
    /Applications/LibreOffice.app/Contents/MacOS/soffice, C:\\Program Files\\LibreOffice\\program\\soffice.exe."""
    raise NotImplementedError


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
    raise NotImplementedError
