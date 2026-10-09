"""Template spec + the one deterministic certificate renderer (used to issue AND to rebuild the expected page)."""
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core import FONTS_DIR, TEMPLATES_DIR

MARGIN = 4  # px of clear space kept inside a field bbox on each side
MIN_SIZE = 12


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((TEMPLATES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def load_template(name: str = "cert-v1") -> dict:
    """Parsed core.TEMPLATES_DIR/<name>.json, cached."""
    return _load(name)


def zones(name: str = "cert-v1") -> dict[str, dict]:
    """{field key: field spec from the template} in template order."""
    return {f["key"]: f for f in load_template(name)["fields"]}


@lru_cache(maxsize=None)
def _font(tpl: str, font_key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / load_template(tpl)["fonts"][font_key]), size)


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def draw_field(image: np.ndarray, key: str, text: str) -> None:
    """In place: fill the field's bbox with white, then draw `text` with the field's font/size/align,
    vertically centered in the bbox, color template["value_color"]. Shared by render_certificate and devtools/tamper.py."""
    tpl = "cert-v1"
    t = load_template(tpl)
    f = zones(tpl)[key]
    x, y, w, h = f["bbox"]
    crop = Image.new("RGB", (w, h), "white")
    size = f["size"]
    while True:
        font = _font(tpl, f["font"], size)
        l, _, r, _ = font.getbbox(text, anchor="lm")
        if r - l <= w - 2 * MARGIN or size <= MIN_SIZE:
            break
        size -= 1  # shrink step by step until the value fits
    ax, anchor = {"left": (MARGIN, "lm"), "center": (w / 2, "mm"), "right": (w - MARGIN, "rm")}[f["align"]]
    ImageDraw.Draw(crop).text((ax, h / 2), text, font=font, fill=_rgb(t["value_color"]), anchor=anchor)
    image[y:y + h, x:x + w] = np.asarray(crop)[:, :, ::-1]


def render_certificate(fields: dict[str, str], meta: dict) -> np.ndarray:
    """BGR uint8 (1654, 2339, 3). Pure function of its arguments: same input -> byte-identical output.

    fields: long keys (name, student_id, program, award, grade, date_issued).
    meta: {"seal": str | None, "doc_id": str, "version": int, "markers": bool = True}
      - seal None  -> QR box left blank (and its caption skipped)
      - markers False -> no ArUco markers
      - doc_id falsy -> footer skipped
    Draws: white page, border, decor text/lines, field labels (label spec, at bbox x, bbox y + offset_y, left-top anchored),
    field values (draw_field), ArUco markers (cv2.aruco.generateImageMarker), QR (core.qr.render_qr into qr.bbox).
    Fonts only from core.FONTS_DIR via PIL.ImageFont.truetype.
    """
    tpl = "cert-v1"
    t = load_template(tpl)
    W, H = t["page"]["width"], t["page"]["height"]
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    b = t["border"]
    d.rectangle([b["inset"], b["inset"], W - 1 - b["inset"], H - 1 - b["inset"]], outline=b["color"], width=b["thickness"])

    qx, qy, qw, qh = t["qr"]["bbox"]
    seal = meta.get("seal")
    for s in t["decor"]["text"]:
        x, y = s["xy"]
        if not seal and qx <= x <= qx + qw and qy - 60 <= y < qy:
            continue  # QR caption
        d.text((x, y), s["text"], font=_font(tpl, s["font"], s["size"]), fill=s["color"], anchor=s["anchor"])
    for ln in t["decor"]["lines"]:
        d.line([tuple(ln["from"]), tuple(ln["to"])], fill=ln["color"], width=ln["width"])
    ft = t["decor"]["footer"]
    if meta.get("doc_id"):
        d.text(tuple(ft["xy"]), ft["text"].format(doc_id=meta["doc_id"], version=meta.get("version", 1)),
               font=_font(tpl, ft["font"], ft["size"]), fill=ft["color"], anchor=ft["anchor"])
    lab = t["label"]
    for f in t["fields"]:
        if f["label"]:
            d.text((f["bbox"][0], f["bbox"][1] + lab["offset_y"]), f["label"],
                   font=_font(tpl, lab["font"], lab["size"]), fill=lab["color"], anchor="la")

    out = np.ascontiguousarray(np.asarray(img)[:, :, ::-1])
    for key, f in zones(tpl).items():
        draw_field(out, key, fields.get(key, ""))

    if meta.get("markers", True):
        m = t["markers"]
        dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, m["dictionary"]))
        for it in m["items"]:
            g = cv2.aruco.generateImageMarker(dic, it["id"], m["size"])
            out[it["y"]:it["y"] + m["size"], it["x"]:it["x"] + m["size"]] = g[:, :, None]
    if seal:
        from core import qr  # late import: module-level attribute lookup keeps it monkeypatchable
        out[qy:qy + qh, qx:qx + qw] = qr.render_qr(seal, qw)[:, :, None]
    return out


def save_png(image: np.ndarray, path: Path) -> None:
    Image.fromarray(image[:, :, ::-1]).save(path, "PNG")


def save_pdf(image: np.ndarray, path: Path) -> None:
    """Single-page PDF at the template DPI (Pillow, resolution=200) so pypdfium2 at 200 DPI gives back 2339x1654."""
    Image.fromarray(image[:, :, ::-1]).save(path, "PDF", resolution=float(load_template()["page"]["dpi"]))
