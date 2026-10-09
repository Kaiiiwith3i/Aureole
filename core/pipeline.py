"""issue() / reissue() / revoke() / verify(). Orchestrator-owned. See CONTRACTS.md."""
import secrets
import time
import uuid

import cv2
import numpy as np

from app.schemas import CertFields, FieldResult, Finding, Report, ReportImages
from core import align, classify, compare, data_dir, diff, forensics, ocr, qr, seal, template
from core.registry import Registry

MAX_SIDE = 3000  # px; larger inputs are downscaled
ZONE_MARGIN = 8  # px around a field zone when cropping for OCR
NOTE_CONF = 0.6  # a finding at or above this confidence affects the verdict
MIN_ZONE_PIXELS = 30  # changed pixels inside a zone before a region counts as touching that field

HEADLINES = {
    "AUTHENTIC": "Seal verified. Every protected field matches the issuer's record.",
    "AUTHENTIC_WITH_NOTES": "Seal verified and every protected field matches. We found extra markings outside the protected areas.",
    "INVALID_SEAL": "This seal wasn't issued by a trusted issuer.",
}
MESSAGES = {
    "stamp": "A stamp was added {where}.",
    "handwriting": "Handwriting or pen marks were added {where}.",
    "physical_damage": "A stain or physical damage is visible {where}.",
    "fold": "A fold or crease is visible {where}.",
    "text_change": "The text {where} differs from the issued original.",
    "unknown": "Minor difference, likely capture noise.",
}


# ---------------------------------------------------------------- issuing

def _publish(doc_id: str, version: int, fields: dict[str, str]) -> dict:
    fields = CertFields(**fields).model_dump()  # trust boundary: same caps as the API
    key, kid = seal.load_or_create_issuer_key()
    text = seal.make_seal(fields, doc_id, version, key)
    image = template.render_certificate(fields, {"seal": text, "doc_id": doc_id, "version": version})
    out = data_dir() / "issued"
    out.mkdir(exist_ok=True)
    png, pdf = out / f"{doc_id}_v{version}.png", out / f"{doc_id}_v{version}.pdf"
    template.save_png(image, png)
    template.save_pdf(image, pdf)
    Registry().issue(doc_id, version, kid, fields, text)
    return {"doc_id": doc_id, "version": version, "seal": text, "png_path": png, "pdf_path": pdf}


def issue(fields: dict[str, str]) -> dict:
    """Sign, render, save PNG+PDF under data_dir()/issued/, register.
    Returns {"doc_id", "version", "seal", "png_path", "pdf_path"} (paths are pathlib.Path). ValueError on invalid fields."""
    return _publish(secrets.token_hex(4), 1, fields)


def reissue(doc_id: str, fields: dict[str, str]) -> dict:
    """New version of an existing doc_id; the old one becomes superseded. Same return shape as issue(). KeyError if unknown."""
    registry = Registry()
    if registry.get(doc_id) is None:
        raise KeyError(doc_id)
    return _publish(doc_id, registry.next_version(doc_id), fields)


def revoke(doc_id: str) -> bool:
    return Registry().revoke(doc_id)


# ---------------------------------------------------------------- verifying

def _load(data: bytes) -> np.ndarray:
    if data[:5] == b"%PDF-":
        import pypdfium2 as pdfium

        page = pdfium.PdfDocument(data)[0]
        image = np.array(page.render(scale=200 / 72).to_pil().convert("RGB"))[:, :, ::-1].copy()
    else:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("This file isn't a readable PNG, JPG or PDF.")
    scale = MAX_SIDE / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image


def _zone_of(region, zones: dict) -> str | None:
    """The protected zone holding the most changed pixels of this region (mask-based, so a diagonal crease's bbox doesn't count)."""
    rx, ry, rw, rh = region.bbox
    best, best_px = None, MIN_ZONE_PIXELS - 1
    for key, z in zones.items():
        x, y, w, h = z["bbox"]
        x0, y0, x1, y1 = max(rx, x), max(ry, y), min(rx + rw, x + w), min(ry + rh, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        px = int(np.count_nonzero(region.mask[y0 - ry:y1 - ry, x0 - rx:x1 - rx]))
        if px > best_px:
            best, best_px = key, px
    return best


def _label(key: str, zones: dict) -> str:
    return zones[key]["label"] or key.replace("_", " ").title()


def _decide(status: str, current_version, aligned: bool, fields: list[FieldResult], findings: list[Finding], zones: dict) -> tuple[str, str]:
    """(verdict, headline) for a document whose seal verified. Order is the contract's."""
    if status == "superseded":
        return "REVOKED", f"This seal is genuine, but the issuer replaced this document with version {current_version}."
    if status == "revoked":
        return "REVOKED", "This seal is genuine, but the issuer has revoked this document."
    by_key = {f.key: f for f in fields}
    bad = next((f for f in fields if f.status == "MISMATCH"), None)
    if bad is None:
        hit = next((x for x in findings if x.type == "text_change" and x.confidence >= NOTE_CONF
                    and x.field and by_key[x.field].status != "UNREADABLE"), None)
        bad = by_key[hit.field] if hit else None
    if bad is not None:
        name = _label(bad.key, zones).lower()
        if compare.normalize(bad.read) == compare.normalize(bad.signed):  # caught by the visual diff, not by OCR
            return "MISMATCH", f'The printed {name} looks altered compared with the sealed record ("{bad.signed}").'
        return "MISMATCH", f'The printed {name} doesn\'t match the sealed record: sealed "{bad.signed}", printed "{bad.read}".'
    if not aligned:
        return "INCONCLUSIVE", "Seal verified, but we couldn't read the page clearly enough to confirm it. Try a sharper photo."
    unread = next((f for f in fields if f.status == "UNREADABLE"), None)
    if unread is not None:
        return "INCONCLUSIVE", f"Seal verified, but we couldn't read {_label(unread.key, zones).lower()} clearly enough to confirm it. Try a sharper photo."
    notes = [x for x in findings if x.type != "unknown" and x.confidence >= NOTE_CONF]
    if notes:
        if any(x.field for x in notes):
            return "AUTHENTIC_WITH_NOTES", "Seal verified and every protected field matches. We found extra markings, some touching protected areas."
        return "AUTHENTIC_WITH_NOTES", HEADLINES["AUTHENTIC_WITH_NOTES"]
    return "AUTHENTIC", HEADLINES["AUTHENTIC"]


def verify(data: bytes, filename: str = "upload") -> Report:
    """Verify PNG/JPG/PDF bytes. Raises ValueError only when the file can't be decoded as an image or PDF."""
    start = last = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str) -> None:
        nonlocal last
        now = time.perf_counter()
        timings[name] = round(timings.get(name, 0) + (now - last) * 1000, 1)
        last = now

    image = _load(data)
    lap("load")
    rid = uuid.uuid4().hex[:12]
    out = data_dir() / "reports" / rid
    out.mkdir(parents=True)
    urls: dict[str, str] = {}

    def save(name: str, img: np.ndarray) -> None:
        cv2.imwrite(str(out / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        urls[name] = f"/reports/{rid}/{name}.jpg"

    def done(report: Report) -> Report:
        lap("write")
        timings["total"] = round((time.perf_counter() - start) * 1000, 1)
        report.images, report.timings = ReportImages(**urls), timings
        return report

    report = Report(report_id=rid, filename=filename, verdict="NO_SEAL", headline="", image_size=[image.shape[1], image.shape[0]])
    code = qr.decode_qr(image)
    lap("qr")

    if code is None:  # forensics only
        ela = forensics.ela(image)
        hits = forensics.copy_move(image)
        lap("forensics")
        for i, hit in enumerate(hits, 1):
            for part, box in (("a", hit.src), ("b", hit.dst)):
                report.findings.append(Finding(
                    id=f"f{i}{part}", type="digital_edit", bbox=list(box), severity="warning", confidence=round(hit.confidence, 2),
                    message="This area and another part of the page are near-identical copies, which suggests one of them was pasted in."))
        found = f"found {len(hits)} region(s) that look digitally modified." if hits else "found no signs of digital modification."
        report.headline = f"No seal found, so authenticity can't be confirmed. Forensic analysis {found}"
        save("scan", image)
        save("ela", forensics.heatmap(ela))
        return done(report)

    check = seal.verify_seal(code.text, seal.load_trusted_keys())
    lap("seal")
    if check.data is not None:
        report.doc_id, report.version, report.kid = check.data.doc_id, check.data.version, check.data.kid
    if not check.ok:  # nothing on the page can be trusted, so nothing else is compared
        report.verdict, report.headline = "INVALID_SEAL", HEADLINES["INVALID_SEAL"]
        save("scan", image)
        return done(report)

    signed = check.data
    entry = Registry().get(signed.doc_id, signed.version)
    report.registry_status = entry["status"] if entry else "unknown"
    report.current_version = entry["current_version"] if entry and entry["status"] == "superseded" else None
    if entry is None:
        report.notes.append("This document isn't in the local registry, so we couldn't check whether it was revoked.")

    tpl, zones = template.load_template(), template.zones()
    aligned = align.align(image, code.corners, qr.symbol_quad(code.text, tpl["qr"]["bbox"]))
    lap("align")
    if aligned is None:
        report.verdict, report.headline = _decide(report.registry_status, report.current_version, False, [], [], zones)
        save("scan", image)
        return done(report)

    scan = aligned.image
    report.image_size = [scan.shape[1], scan.shape[0]]
    expected = template.render_certificate(signed.fields, {"seal": code.text, "doc_id": signed.doc_id, "version": signed.version})
    lap("render")

    m = ZONE_MARGIN
    for key, z in zones.items():
        x, y, w, h = z["bbox"]
        read = ocr.read_text(scan[y - m:y + h + m, x - m:x + w + m])
        result = compare.compare_field(signed.fields[key], read.text, read.confidence, z["numeric"])
        report.fields.append(FieldResult(
            key=key, label=_label(key, zones), signed=signed.fields[key], read=read.text, status=result.status,
            similarity=round(result.similarity, 3), confidence=round(read.confidence, 3)))
    lap("ocr")

    size = tpl["markers"]["size"]
    ignore = [[mk["x"] - 12, mk["y"] - 12, size + 24, size + 24] for mk in tpl["markers"]["items"]]
    qx, qy, qw, qh = tpl["qr"]["bbox"]
    ignore.append([qx - 6, qy - 6, qw + 12, qh + 12])
    regions = diff.diff_regions(expected, scan, ignore)
    lap("diff")
    ela = cv2.warpPerspective(forensics.ela(image), aligned.H, (scan.shape[1], scan.shape[0]))
    lap("forensics")

    zone_boxes = [z["bbox"] for z in zones.values()]
    for i, region in enumerate(regions, 1):
        kind, conf = classify.classify(classify.extract_features(scan, expected, region, zone_boxes, ela))
        field = _zone_of(region, zones)
        where = f"over the {_label(field, zones).lower()} field" if field else "outside the protected areas"
        severity = "info" if not field else "critical" if kind == "text_change" else "warning"
        report.findings.append(Finding(
            id=f"f{i}", type=kind, bbox=[int(v) for v in region.bbox], field=field, severity=severity,
            confidence=round(float(conf), 2), message=MESSAGES[kind].format(where=where)))
    lap("classify")

    for f in report.fields:  # every MISMATCH field is highlighted, whether or not the visual diff caught it
        if f.status == "MISMATCH" and not any(x.field == f.key and x.type == "text_change" for x in report.findings):
            report.findings.append(Finding(
                id=f"m-{f.key}", type="text_change", bbox=list(zones[f.key]["bbox"]), field=f.key, severity="critical",
                confidence=f.confidence, message=f'The printed {f.label.lower()} reads "{f.read}", but the sealed value is "{f.signed}".'))
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    report.findings.sort(key=lambda x: (x.type == "unknown", severity_rank[x.severity], -x.confidence))

    report.verdict, report.headline = _decide(report.registry_status, report.current_version, True, report.fields, report.findings, zones)
    save("scan", scan)
    save("expected", expected)
    save("diff", diff.diff_overlay(scan, regions))
    save("ela", forensics.heatmap(ela))
    return done(report)
