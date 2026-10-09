import ctypes
import io
import time

import cv2
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
import pytest
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR, align, convert, layout, lines, ocr, seal, stamp
from devtools.photo_sim import simulate_photo

TEXT = ["Republic of the Philippines", "Hon. Juan Peñaflor, Registrar", "2024-10482",
        "Maria Santos earned a GWA of 1.25 this term", "Issued at Quezon City on the tenth of October"]


@pytest.fixture(scope="module", autouse=True)
def _warm():
    ocr.warm_up()


def issue(text_lines, tmp_path_factory):
    content, _ = convert.to_pdf("\n".join(text_lines).encode(), "doc.txt")
    key, _ = seal.load_or_create_issuer_key(tmp_path_factory.mktemp("keys"))
    pdf = stamp.stamp(content, "a1b2c3d4", 1, key, "2026-10-10")
    return pdf, stamp.render_page(pdf, 0)


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    pdf, img = issue(TEXT, tmp_path_factory)
    return pdf, img, lines.page_lines(pdf, 0, img)


def test_one_line_per_input_line(page):
    _, _, L = page
    assert [l["text"] for l in L] == TEXT
    assert [l["numeric"] for l in L] == [False, False, True, False, False]
    assert all(l["readable"] for l in L)
    ys = [l["bbox"][1] for l in L]
    assert ys == sorted(ys)


def test_boxes_contain_ink_and_nothing_between(page):
    _, img, L = page
    dark = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 128
    inside = np.zeros_like(dark)
    for l in L:
        x, y, w, h = l["bbox"]
        assert dark[y:y + h, x:x + w].sum() > 30
        inside[y:y + h, x:x + w] = True
    c = layout.layout(False).content
    outside = dark[c[1]:c[1] + c[3], c[0]:c[0] + c[2]] & ~inside[c[1]:c[1] + c[3], c[0]:c[0] + c[2]]
    assert outside.sum() < 20  # the frame footer/QR/markers lie outside the content box


def test_frame_makes_no_lines(page):
    c = layout.layout(False).content
    for l in page[2]:
        x, y, w, h = l["bbox"]
        assert x >= c[0] - 4 and y >= c[1] - 4 and y + h <= c[1] + c[3] + 4


def two_column_pdf():
    doc = pdfium.PdfDocument.new()
    p = doc.new_page(595, 842)
    font = raw.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
    for txt, x in (("Item", 60), ("Amount 1,250.00", 400)):
        obj = raw.FPDFPageObj_CreateTextObj(doc.raw, font, 11)
        w = (txt + "\0").encode("utf-16-le")
        raw.FPDFText_SetText(obj, ctypes.cast(ctypes.create_string_buffer(w, len(w)), ctypes.POINTER(ctypes.c_ushort)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, 700)
        raw.FPDFPage_InsertObject(p.raw, obj)
    p.gen_content()
    b = io.BytesIO()
    doc.save(b)
    return b.getvalue()


def test_two_column_split(tmp_path):
    key, _ = seal.load_or_create_issuer_key(tmp_path / "keys")
    pdf = stamp.stamp(two_column_pdf(), "a1b2c3d4", 1, key, "2026-10-10")
    L = lines.page_lines(pdf, 0, stamp.render_page(pdf, 0))
    assert [l["text"] for l in L] == ["Item", "Amount 1,250.00"]
    assert L[1]["numeric"] is False and L[0]["bbox"][0] < L[1]["bbox"][0]


def edit(img, bbox, old, new, which):
    """White-paint `old` (a substring) of the line and draw `new` in its place; crude but exact enough for OCR."""
    x, y, w, h = bbox
    out = img.copy()
    pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    f = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), int(h * 0.82 / 1.2 * 1.0))
    d.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], fill="white")
    d.text((x + 2, y + h // 2), which, fill=(17, 17, 17), font=f, anchor="lm")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def test_check_line_match_clean(page):
    _, img, L = page
    assert all(lines.check_line(img, img, l).status == "MATCH" for l in L)


@pytest.mark.parametrize("idx,new", [(3, "Maria Santoz earned a GWA of 1.25 this term"),
                                     (3, "Maria Santos earned a GWA of 1.75 this term")])
def test_mismatch_on_one_char(page, idx, new):
    _, img, L = page
    scan = edit(img, L[idx]["bbox"], "", new, new)
    r = lines.check_line(scan, img, L[idx])
    assert r.status == "MISMATCH", r


def test_unreadable_when_blurred_or_noised(page):
    _, img, L = page
    x, y, w, h = L[3]["bbox"]
    blur = img.copy()
    blur[y - 8:y + h + 8, x - 8:x + w + 8] = cv2.GaussianBlur(img[y - 8:y + h + 8, x - 8:x + w + 8], (0, 0), 9)
    assert lines.check_line(blur, img, L[3]).status == "UNREADABLE"
    noise = img.copy()
    rng = np.random.default_rng(1)
    noise[y - 8:y + h + 8, x - 8:x + w + 8] = rng.integers(90, 170, (h + 16, w + 16, 1), dtype=np.uint8).repeat(3, 2)
    assert lines.check_line(noise, img, L[3]).status == "UNREADABLE"


def test_red_stamp_still_matches(page):
    _, img, L = page
    x, y, w, h = L[3]["bbox"]
    over = img.copy()  # stamp ink multiplies: white paper turns red, black text stays black
    r = over[y - 4:y + h + 4, x + w // 4:x + w // 2].astype(np.float32)
    over[y - 4:y + h + 4, x + w // 4:x + w // 2] = (r * np.float32([0.3, 0.3, 1.0])).astype(np.uint8)
    assert lines.check_line(over, img, L[3]).status == "MATCH"


def test_photo_roundtrip_all_lines_match(page):
    _, img, L = page
    photo = simulate_photo(img, seed=3)
    ok, buf = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 75])
    res = align.align(cv2.imdecode(buf, cv2.IMREAD_COLOR))
    assert [lines.check_line(res.image, img, l).status for l in L] == ["MATCH"] * len(L)


def test_image_only_page_uses_ocr(tmp_path):
    im = Image.new("RGB", (1654, 2339), "white")
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), 44)
    for i, t in enumerate(["Certificate of Residency", "Barangay San Roque 2024-5531"]):
        d.text((300, 400 + i * 120), t, fill=(17, 17, 17), font=f)
    b = io.BytesIO()
    im.save(b, "PDF", resolution=200)
    key, _ = seal.load_or_create_issuer_key(tmp_path / "keys")
    pdf = stamp.stamp(b.getvalue(), "a1b2c3d4", 1, key, "2026-10-10")
    L = lines.page_lines(pdf, 0, stamp.render_page(pdf, 0))
    assert [l["text"] for l in L] == ["Certificate of Residency", "Barangay San Roque 2024-5531"]
    assert all(l["readable"] for l in L)


def test_dense_page_speed(tmp_path_factory):
    dense = [f"Row {i} the quick brown fox jumps over the lazy dog {i * 37}" for i in range(50)]
    pdf, img = issue(dense, tmp_path_factory)
    t = time.perf_counter()
    L = lines.page_lines(pdf, 0, img)
    dt = time.perf_counter() - t
    assert len(L) == 50 and dt < 3, (len(L), dt)
