"""Frame every page of a content PDF with markers, the signed QR seal and the footer; render pages. Builder B."""
import hashlib
from io import BytesIO

import cv2
import numpy as np
import pypdfium2 as pdfium
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR, layout, qr, seal

_FONT = str(FONTS_DIR / "DejaVuSans.ttf")


def fingerprint(content_pdf: bytes) -> str:
    """First 16 hex chars of SHA-256 of the content PDF."""
    return hashlib.sha256(content_pdf).hexdigest()[:16]


def page_count(pdf: bytes) -> int:
    doc = pdfium.PdfDocument(pdf)
    n = len(doc)
    doc.close()
    return n


def _put_image(out, page, gray_or_rgb: np.ndarray, box: list[int], page_h: int) -> None:
    x, y, w, h = box
    img = pdfium.PdfImage.new(out)
    img.set_bitmap(pdfium.PdfBitmap.from_pil(Image.fromarray(gray_or_rgb).convert("RGB")))
    img.set_matrix(pdfium.PdfMatrix().scale(w * layout.PT, h * layout.PT).translate(x * layout.PT, (page_h - y - h) * layout.PT))
    page.insert_obj(img)


def _footer(lines: list[str], size: tuple[int, int]) -> np.ndarray:
    w, h = size
    px = 34
    while px > 8:
        font = ImageFont.truetype(_FONT, px)
        if max(font.getlength(s) for s in lines) <= w and px * 1.35 * len(lines) <= h:
            break
        px -= 1
    img = Image.new("L", size, 255)
    d = ImageDraw.Draw(img)
    for i, s in enumerate(lines):
        d.text((0, int(i * px * 1.35)), s, font=font, fill=0)
    return np.asarray(img)


def stamp(content_pdf: bytes, doc_id: str, version: int, private_key: Ed25519PrivateKey, issued_on: str) -> bytes:
    """The issued PDF. Every output page is A4 (portrait or landscape, following the source page), laid out by
    core.layout: the source page embedded as a form XObject (vector, text stays selectable) fitted into layout.content,
    the four ArUco markers, the QR of seal.make_seal(doc_id, version, p, n, fingerprint(content_pdf), private_key)
    rendered with qr.render_qr, and the footer text inside layout.footer:
        Aureole document <doc_id> v<version> - page <p> of <n>
        Fingerprint <h in groups of 4>
        Issued <issued_on>. Verify this page with the issuing office.
    Markers, QR and footer are drawn in black on white. issued_on is YYYY-MM-DD."""
    src = pdfium.PdfDocument(content_pdf)
    out = pdfium.PdfDocument.new()
    n, h16 = len(src), fingerprint(content_pdf)
    aruco = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, layout.DICTIONARY))
    for i in range(n):
        sp = src[i]
        sw, sh = sp.get_size()  # ponytail: pdfium's form XObject already applies /Rotate and the crop-box origin, so (0,0)-(sw,sh) is the upright page
        L = layout.layout(sw > sh)
        W, H = L.size
        page = out.new_page(W * layout.PT, H * layout.PT)
        cx, cy, cw, ch = L.content
        s = min(cw * layout.PT / sw, ch * layout.PT / sh)
        tx = (cx + (cw - sw * s / layout.PT) / 2) * layout.PT
        ty = (H - cy - ch + (ch - sh * s / layout.PT) / 2) * layout.PT
        obj = src.page_as_xobject(i, out).as_pageobject()
        obj.set_matrix(pdfium.PdfMatrix().scale(s, s).translate(tx, ty))
        page.insert_obj(obj)
        for mid, (x, y) in L.markers.items():
            _put_image(out, page, cv2.aruco.generateImageMarker(aruco, mid, layout.MARKER), [x, y, layout.MARKER, layout.MARKER], H)
        text = seal.make_seal(doc_id, version, i + 1, n, h16, private_key)
        _put_image(out, page, qr.render_qr(text, layout.QR), L.qr, H)
        lines = [f"Aureole document {doc_id} v{version} - page {i + 1} of {n}",
                 "Fingerprint " + " ".join(h16[j:j + 4] for j in range(0, 16, 4)),
                 f"Issued {issued_on}. Verify this page with the issuing office."]
        _put_image(out, page, _footer(lines, (L.footer[2], L.footer[3])), L.footer, H)
        page.gen_content()
    buf = BytesIO()
    out.save(buf)
    return buf.getvalue()


def render_page(pdf: bytes, index: int) -> np.ndarray:
    """BGR render of page `index` (0-based) at 200 DPI. For an issued PDF the result is exactly layout(...).size
    (resize by a pixel if rounding differs)."""
    doc = pdfium.PdfDocument(pdf)
    img = doc[index].render(scale=layout.DPI / 72).to_numpy()
    doc.close()
    if img.shape[2] == 4:
        img = img[..., :3]
    h, w = img.shape[:2]
    want = layout.layout(w > h).size
    if (w, h) != want and abs(w - want[0]) <= 2 and abs(h - want[1]) <= 2:
        img = cv2.resize(img, want, interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(img)
