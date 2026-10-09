"""issue() / reissue() / revoke() / verify(). Orchestrator-owned. See CONTRACTS.md."""
import hashlib
import json
import secrets
import time
import uuid
from datetime import date
from pathlib import Path

import cv2
import numpy as np

from app.schemas import Finding, LineResult, PageReport, Report, ReportImages
from core import align, classify, convert, data_dir, diff, forensics, layout, lines, ocr, qr, seal, stamp
from core.registry import Registry

MAX_SIDE = 3000  # px; larger inputs are downscaled
NOTE_CONF = 0.6  # a finding at or above this confidence affects the verdict
MIN_LINE_PIXELS = 30  # changed pixels inside a line's box before a region counts as touching that line
ADDED_TEXT_CHARS = 4  # letters/digits OCR must read in a region off every line before it counts as added text
RANK = ["INVALID_SEAL", "NOT_ISSUED", "REVOKED", "MODIFIED", "INCONCLUSIVE", "AUTHENTIC_WITH_NOTES", "AUTHENTIC"]  # worst first

HEADLINES = {
    "digital": "This file is identical to the issued document.",
    "AUTHENTIC": "Seal verified. No differences from the issued document were found.",
    "AUTHENTIC_WITH_NOTES": "Seal verified and the text matches the issued document. We found extra markings on the page.",
    "revoked": "This seal is genuine, but the issuer has revoked this document.",
    "superseded": "This seal is genuine, but the issuer replaced this document with version {n}.",
    "unread": "Seal verified, but parts of the page couldn't be read clearly enough to confirm them. Try a sharper photo.",
    "no_qr": "This looks like a Signet page, but we couldn't read its seal. Try a flatter, sharper photo.",
    "INVALID_SEAL": "This seal wasn't issued by a trusted issuer.",
    "no_seal": "No Signet seal was found, so this isn't a document issued by this system.",
    "no_record": "This seal has no matching record in the registry.",
    "other_doc": "This page belongs to a different issued document.",
    "different": "The content of this page is different from the document this seal was issued for.",
    "added": "Text was added to this page that isn't in the issued document.",
    "altered": "A line on this page looks altered compared with the issued document.",
}
MESSAGES = {
    "stamp": "A stamp was added {where}.",
    "handwriting": "Handwriting or pen marks were added {where}.",
    "physical_damage": "A stain or physical damage is visible {where}.",
    "fold": "A fold or crease is visible {where}.",
    "text_change": "The text {where} differs from the issued document.",
    "unknown": "Minor difference, likely capture noise.",
}


# ---------------------------------------------------------------- issuing

def issued_dir(doc_id: str, version: int) -> Path:
    return data_dir() / "issued" / f"{doc_id}_v{version}"


def _publish(doc_id: str, version: int, data: bytes, filename: str, title: str) -> dict:
    content, source_type = convert.to_pdf(data, filename)
    key, kid = seal.load_or_create_issuer_key()
    issued = stamp.stamp(content, doc_id, version, key, date.today().isoformat())
    pages = []
    for i in range(stamp.page_count(issued)):
        image = stamp.render_page(issued, i)
        code = qr.decode_qr(image)
        if code is None or not seal.verify_seal(code.text, seal.load_trusted_keys()).ok:
            raise RuntimeError(f"page {i + 1} of the sealed file failed its own seal check")  # never hand out a file that can't verify
        pages.append({"landscape": image.shape[1] > image.shape[0], "lines": lines.page_lines(issued, i, image)})
    name = Path(filename).name[:120] or "upload"
    out = issued_dir(doc_id, version)
    out.mkdir(parents=True)
    (out / "issued.pdf").write_bytes(issued)
    (out / f"source.{source_type}").write_bytes(data)
    (out / "pages.json").write_text(json.dumps(pages, ensure_ascii=False))
    entry = {"doc_id": doc_id, "version": version, "kid": kid, "title": (title.strip() or Path(name).stem)[:120],
             "source_name": name, "source_type": source_type, "pages": len(pages),
             "source_sha256": hashlib.sha256(data).hexdigest(), "content_sha256": hashlib.sha256(content).hexdigest(),
             "file_sha256": hashlib.sha256(issued).hexdigest()}
    Registry().issue(entry)
    return {"doc_id": doc_id, "version": version, "title": entry["title"], "pages": len(pages),
            "fingerprint": entry["content_sha256"][:16], "pdf_path": out / "issued.pdf"}


def issue(data: bytes, filename: str, title: str = "") -> dict:
    """Convert, seal, store and register an upload.
    Returns {"doc_id", "version", "title", "pages", "fingerprint", "pdf_path"}. ValueError when it can't be issued."""
    return _publish(secrets.token_hex(4), 1, data, filename, title)


def reissue(doc_id: str, data: bytes, filename: str, title: str = "") -> dict:
    """New version of an existing doc_id; the old one becomes superseded. KeyError if unknown."""
    registry = Registry()
    old = registry.get(doc_id)
    if old is None:
        raise KeyError(doc_id)
    return _publish(doc_id, registry.next_version(doc_id), data, filename, title or old["title"])


def revoke(doc_id: str) -> bool:
    return Registry().revoke(doc_id)


# ---------------------------------------------------------------- verifying

def _load(files: list[tuple[str, bytes]]) -> list[np.ndarray]:
    """Every page of every upload as a BGR image, in upload order."""
    images = []
    for _, data in files:
        try:
            if data[:5] == b"%PDF-":
                batch = [stamp.render_page(data, i) for i in range(min(stamp.page_count(data), layout.MAX_PAGES + 1))]
            else:
                batch = [cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)]
        except Exception:  # empty, truncated, corrupt or password-protected: the decoders raise their own error types
            batch = [None]
        if not batch or any(im is None or im.size == 0 for im in batch):
            raise ValueError("One of these files isn't a readable PNG, JPG or PDF.")
        images += batch
    if not 1 <= len(images) <= layout.MAX_PAGES:
        raise ValueError(f"Send between 1 and {layout.MAX_PAGES} pages at a time.")
    for i, im in enumerate(images):
        scale = MAX_SIDE / max(im.shape[:2])
        if scale < 1:
            images[i] = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return images


def _line_of(region, page_lines: list[dict]) -> int | None:
    """Index of the line holding the most changed pixels of this region (mask-based, so a diagonal crease's bbox doesn't count)."""
    rx, ry, rw, rh = region.bbox
    best, best_px = None, MIN_LINE_PIXELS - 1
    for i, line in enumerate(page_lines):
        x, y, w, h = line["bbox"]
        x0, y0, x1, y1 = max(rx, x), max(ry, y), min(rx + rw, x + w), min(ry + rh, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        px = int(np.count_nonzero(region.mask[y0 - ry:y1 - ry, x0 - rx:x1 - rx]))
        if px > best_px:
            best, best_px = i, px
    return best


def _letters(text: str) -> str:
    return "".join(c for c in text if c.isalnum())


def _added_text(scan: np.ndarray, region) -> float:
    """OCR confidence if the ink this region added reads as printed text, else 0. Only the changed pixels are read
    (everything else is painted white), so genuine text next to the region can't be mistaken for an addition."""
    if region.added < 0.5:
        return 0.0
    x, y, w, h = region.bbox
    crop = lines.ink_only(scan[y:y + h, x:x + w])
    crop[cv2.dilate(region.mask, np.ones((7, 7), np.uint8)) == 0] = 255
    read = ocr.read_text(crop)
    return read.confidence if read.confidence >= 0.8 and len(_letters(read.text)) >= ADDED_TEXT_CHARS else 0.0


def _decide(status: str, current_version, aligned: bool, results: list[LineResult], checked: int, findings: list[Finding]) -> tuple[str, str]:
    """(verdict, headline) for a page whose seal verified and is in the registry. Order is the contract's.
    `results` holds the lines that didn't match; `checked` is how many lines were read."""
    if status == "superseded":
        return "REVOKED", HEADLINES["superseded"].format(n=current_version)
    if status == "revoked":
        return "REVOKED", HEADLINES["revoked"]
    unreadable = {r.index for r in results if r.status == "UNREADABLE"}
    mismatched = [r for r in results if r.status == "MISMATCH"]
    change = next((x for x in findings if x.type == "text_change" and x.confidence >= NOTE_CONF and x.line not in unreadable), None)
    if mismatched or change:
        if checked and len(results) > checked / 2:
            return "MODIFIED", HEADLINES["different"]
        if mismatched:
            return "MODIFIED", f"{len(mismatched)} line(s) on this page don't match the issued document."
        return "MODIFIED", HEADLINES["added" if change.line is None else "altered"]
    if not aligned or unreadable:
        return "INCONCLUSIVE", HEADLINES["unread"]
    if any(x.type != "unknown" and x.confidence >= NOTE_CONF for x in findings):
        return "AUTHENTIC_WITH_NOTES", HEADLINES["AUTHENTIC_WITH_NOTES"]
    return "AUTHENTIC", HEADLINES["AUTHENTIC"]


def verify(files: list[tuple[str, bytes]]) -> Report:
    """Verify uploads [(filename, bytes)]: the issued PDF itself, or photos/scans of its pages (PNG/JPG/PDF).
    Raises ValueError only when a file can't be decoded or the page count is out of range."""
    start = last = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str) -> None:
        nonlocal last
        now = time.perf_counter()
        timings[name] = round(timings.get(name, 0) + (now - last) * 1000, 1)
        last = now

    registry = Registry()
    rid = uuid.uuid4().hex[:12]
    name = files[0][0][:120] + (f" (+{len(files) - 1} more)" if len(files) > 1 else "")
    report = Report(report_id=rid, filename=name, mode="pages", verdict="NOT_ISSUED", headline=HEADLINES["no_seal"])

    def known(entry: dict) -> None:
        report.doc_id, report.version, report.kid = entry["doc_id"], entry["version"], entry["kid"]
        report.registry_status, report.pages_total = entry["status"], entry["pages"]
        report.current_version = entry["current_version"] if entry["status"] == "superseded" else None

    exact = registry.find_file(hashlib.sha256(files[0][1]).hexdigest()) if len(files) == 1 else None
    if exact:  # the only exact result: byte-identical to what was issued
        known(exact)
        report.mode, report.pages_checked = "digital", list(range(1, exact["pages"] + 1))
        report.verdict, report.headline = _decide(exact["status"], report.current_version, True, [], 0, [])
        if report.verdict == "AUTHENTIC":
            report.headline = HEADLINES["digital"]
        timings["total"] = round((time.perf_counter() - start) * 1000, 1)
        report.timings = timings
        return report

    images = _load(files)
    lap("load")
    out = data_dir() / "reports" / rid
    out.mkdir(parents=True)
    trusted = seal.load_trusted_keys()
    sealed: list[tuple[PageReport, seal.SealData]] = []  # pages whose seal is in the registry

    for index, image in enumerate(images, 1):
        page = PageReport(index=index, verdict="NOT_ISSUED", headline=HEADLINES["no_seal"], image_size=[image.shape[1], image.shape[0]])
        report.pages.append(page)
        urls: dict[str, str] = {}

        def save(kind: str, img: np.ndarray) -> None:
            cv2.imwrite(str(out / f"{index}_{kind}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            urls[kind] = f"/reports/{rid}/{index}_{kind}.jpg"
            page.images = ReportImages(**urls)

        def signet(c):  # a QR printed inside the document itself (a payment code, a link) is not a seal
            return c if c and c.text.startswith(seal.PREFIX + ".") else None

        code = signet(qr.decode_qr(image))
        if code is None:  # steep angle or glare can defeat the QR reader while the corner markers still read: flatten, look again
            flat = align.align(image)
            if flat is not None:
                image, code = flat.image, signet(qr.decode_qr(flat.image))
                page.image_size = [image.shape[1], image.shape[0]]
                if code is None:  # it is one of ours, so "no seal" would be the wrong thing to say
                    page.verdict, page.headline = "INCONCLUSIVE", HEADLINES["no_qr"]
        lap("qr")
        if code is None:
            save("scan", image)
            continue

        check = seal.verify_seal(code.text, trusted)
        d = check.data
        if d is not None and report.doc_id is None:
            report.doc_id, report.version, report.kid = d.doc_id, d.version, d.kid
        if not check.ok:  # nothing on the page can be trusted, so nothing else is compared
            page.verdict, page.headline = "INVALID_SEAL", HEADLINES["INVALID_SEAL"]
            save("scan", image)
            continue
        page.page = d.page
        entry = registry.get(d.doc_id, d.version)
        if entry is None or entry["kid"] != d.kid or entry["pages"] != d.pages or not entry["content_sha256"].startswith(d.fingerprint):
            page.headline = HEADLINES["no_record"]  # the registry decides, not the signature
            save("scan", image)
            continue
        sealed.append((page, d))
        if len(sealed) == 1:
            known(entry)
        lap("seal")

        folder = issued_dir(d.doc_id, d.version)
        meta = json.loads((folder / "pages.json").read_text())[d.page - 1]
        frame = layout.layout(meta["landscape"])
        aligned = align.align(image, code.corners, qr.symbol_quad(code.text, frame.qr), meta["landscape"])
        if aligned is not None and aligned.layout != frame:
            aligned = None
        lap("align")
        if aligned is None:
            page.verdict, page.headline = _decide(entry["status"], entry["current_version"], False, [], 0, [])
            save("scan", image)
            continue

        scan = aligned.image
        page.image_size = [scan.shape[1], scan.shape[0]]
        expected = stamp.render_page((folder / "issued.pdf").read_bytes(), d.page - 1)
        lap("render")

        page_lines = meta["lines"]
        readable = sorted((i for i, ln in enumerate(page_lines) if ln["readable"]),
                          key=lambda i: -page_lines[i]["bbox"][2] * page_lines[i]["bbox"][3])[:lines.MAX_LINES]
        results: dict[int, LineResult] = {}
        for i in readable:
            c = lines.check_line(scan, expected, page_lines[i])
            if c.status != "MATCH":
                results[i] = LineResult(index=i, bbox=page_lines[i]["bbox"], expected=page_lines[i]["text"], read=c.read, status=c.status,
                                        similarity=round(c.similarity, 3), confidence=round(c.confidence, 3))
        page.lines_total, page.lines_unchecked = len(page_lines), len(page_lines) - len(readable)
        if page.lines_unchecked:
            page.notes.append(f"{page.lines_unchecked} line(s) on this page can't be read by machine and were compared visually only.")
        lap("ocr")

        regions = diff.diff_regions(expected, scan, frame.ignore)
        lap("diff")
        ela = cv2.warpPerspective(forensics.ela(image), aligned.H, (scan.shape[1], scan.shape[0]))
        lap("forensics")

        boxes = [ln["bbox"] for ln in page_lines]
        for n, region in enumerate(regions, 1):
            kind, conf = classify.classify(classify.extract_features(scan, expected, region, boxes, ela))
            line = _line_of(region, page_lines)
            if line is None and (read_conf := _added_text(scan, region)):  # the whole page is protected, not just its lines
                kind, conf = "text_change", max(float(conf), read_conf)
            where = "on a printed line" if line is not None else "outside the printed text"
            severity = "critical" if kind == "text_change" else "warning" if line is not None and kind != "unknown" else "info"
            bbox = [int(v) for v in region.bbox]
            if severity == "critical" and line is not None:  # frame the whole line, one finding per line: keep the more confident
                bbox = page_lines[line]["bbox"]
                same = next((x for x in page.findings if x.severity == "critical" and x.line == line), None)
                if same is not None:
                    if same.confidence >= conf:
                        continue
                    page.findings.remove(same)
            message = "Printed text was added here." if kind == "text_change" and line is None else MESSAGES[kind].format(where=where)
            page.findings.append(Finding(id=f"f{n}", type=kind, bbox=bbox, line=line, severity=severity,
                                         confidence=round(float(conf), 2), message=message))
        lap("classify")

        for i, r in results.items():  # a mark lying on a line makes a differing read unreliable: junk characters are damage, not an edit
            cover = next((x for x in page.findings if x.line == i and x.type not in ("text_change", "unknown")
                          and x.confidence >= NOTE_CONF), None)
            if r.status == "MISMATCH" and cover is not None:
                r.status = "UNREADABLE"
                page.notes.append(f"Something covers a line ({cover.type.replace('_', ' ')}), so its text couldn't be read reliably.")
        for i, r in results.items():  # every MISMATCH line is highlighted, whether or not the visual diff caught it
            if r.status == "MISMATCH" and not any(x.line == i and x.type == "text_change" for x in page.findings):
                page.findings.append(Finding(id=f"m{i}", type="text_change", bbox=r.bbox, line=i, severity="critical", confidence=r.confidence,
                                             message=f'This line reads "{r.read}", which is not what was issued.'))
        severity_rank = {"critical": 0, "warning": 1, "info": 2}
        page.findings.sort(key=lambda x: (x.type == "unknown", severity_rank[x.severity], -x.confidence))
        page.lines = sorted(results.values(), key=lambda r: r.index)
        page.lines_matched = len(readable) - len(results)

        page.verdict, page.headline = _decide(entry["status"], entry["current_version"], True, page.lines, len(readable), page.findings)
        save("scan", scan)
        save("expected", expected)
        save("diff", diff.diff_overlay(scan, regions))
        save("ela", forensics.heatmap(ela))
        lap("write")

    if sealed:
        first = sealed[0][1]
        for page, d in sealed[1:]:
            if (d.doc_id, d.version) != (first.doc_id, first.version):
                page.verdict, page.headline = "MODIFIED", HEADLINES["other_doc"]
        report.pages_checked = sorted({d.page for page, d in sealed if (d.doc_id, d.version) == (first.doc_id, first.version)})
    worst = min(report.pages, key=lambda p: RANK.index(p.verdict))
    report.verdict = worst.verdict
    report.headline = (f"Page {worst.index}: " if len(report.pages) > 1 else "") + worst.headline
    missing = [p for p in range(1, (report.pages_total or 0) + 1) if p not in report.pages_checked]
    if report.verdict in ("AUTHENTIC", "AUTHENTIC_WITH_NOTES") and missing:
        report.verdict = "INCONCLUSIVE"
        report.headline = (f"{len(report.pages_checked)} of {report.pages_total} pages checked with no differences found. "
                           f"Not provided: page {', '.join(map(str, missing))}.")
    timings["total"] = round((time.perf_counter() - start) * 1000, 1)
    report.timings = timings
    return report
