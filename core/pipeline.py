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
import zxingcpp

from app.schemas import Finding, LineResult, PageReport, Report, ReportImages
from core import align, classify, convert, data_dir, diff, forensics, layout, lines, ocr, qr, seal, stamp
from core.registry import Registry

MAX_SIDE = 3000  # px; larger inputs are downscaled
NOTE_CONF = 0.6  # a finding at or above this confidence affects the verdict
MIN_LINE_PIXELS = 30  # changed pixels inside a line's box before a region counts as touching that line
EXTRA_MARK_PIXELS = 80  # a solid blob this big on only one of two copies means their marks differ
BIG_MARK_PIXELS = 1500  # ponytail: an unexplained added mark this big is always a note; set on simulated photos, whose noise never lands inside the content box. Re-measure on real prints.
ADDED_TEXT_CHARS = 4  # letters/digits OCR must read in a region off every line before it counts as added text
RANK = ["INVALID_SEAL", "NOT_ISSUED", "REVOKED", "MODIFIED", "INCONCLUSIVE", "AUTHENTIC_WITH_NOTES", "AUTHENTIC"]  # worst first

HEADLINES = {
    "digital": "This file is identical to the issued document.",
    "approved_exact": "These files are identical to a signed copy approved by issuer staff.",
    "approved_scan": "Printed text matches, and the added marks closely match a copy approved by issuer staff.",
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
    "qr_only": "Seal verified, but the page corners weren't visible enough for a reliable comparison. Try a full-page photo.",
    "different": "The content of this page is different from the document this seal was issued for.",
    "added": "Text was added to this page that isn't in the issued document.",
    "altered": "A line on this page looks altered compared with the issued document.",
    "code": "A QR code or barcode on this page isn't in the issued document.",
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


def _files_digest(files: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    h.update(len(files).to_bytes(2, "big"))
    for _, data in files:
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def _mark_mask(regions: list, size: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(size[::-1], np.uint8)
    for region in regions:
        if region.added < 0.5:
            continue
        x, y, w, h = region.bbox
        mask[y:y + h, x:x + w] |= region.mask
    return mask


def _same_marks(approved: np.ndarray, observed: np.ndarray) -> bool:
    a, b = approved > 0, observed > 0
    if int(a.sum()) < 100:
        return int(b.sum()) < 100
    if int(b.sum()) < 100:
        return False
    kernel = np.ones((5, 5), np.uint8)
    a_near = cv2.dilate(a.astype(np.uint8), kernel) > 0
    b_near = cv2.dilate(b.astype(np.uint8), kernel) > 0
    if (a & b_near).sum() / a.sum() < 0.95 or (b & a_near).sum() / b.sum() < 0.95:
        return False
    # The ratios above let a small extra mark hide beside a large signature, so also refuse any solid blob of ink that
    # only one of the two copies has (opening drops the 1 px fringe that capture misalignment leaves along every stroke).
    for only in (b & ~a_near, a & ~b_near):
        solid = cv2.morphologyEx(only.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        if cv2.connectedComponentsWithStats(solid)[2][1:, cv2.CC_STAT_AREA].max(initial=0) >= EXTRA_MARK_PIXELS:
            return False
    return True


def approve_signed(doc_id: str, files: list[tuple[str, bytes]]) -> dict:
    """Store staff-approved signature marks after verifying all printed content against the issued copy."""
    registry = Registry()
    digest = _files_digest(files)
    if old := registry.find_approval(digest):
        if old["doc_id"] != doc_id:
            raise ValueError("This signed copy belongs to another document.")
        return old
    report = verify(files)
    if report.mode != "pages":
        raise ValueError("Upload scans or photos of the signed pages, not the issued PDF itself.")
    if report.doc_id != doc_id:
        raise ValueError("These pages don't carry this document's seal.")
    if report.registry_status != "active":
        raise ValueError("This version has been revoked or replaced, so a signed copy of it can't be approved.")
    if (report.pages_checked != list(range(1, report.pages_total + 1)) or len(report.pages) != report.pages_total
            or report.verdict not in ("AUTHENTIC", "AUTHENTIC_WITH_NOTES")):
        raise ValueError("The full document must match its issued text before a signed copy can be approved.")
    folder = data_dir() / "approved" / uuid.uuid4().hex[:12]
    masks = {}
    for page in report.pages:
        scan = cv2.imread(str(data_dir() / "reports" / report.report_id / f"{page.index}_scan.jpg"))
        issued = (issued_dir(doc_id, report.version) / "issued.pdf").read_bytes()
        expected = stamp.render_page(issued, page.page - 1)
        frame = layout.layout(expected.shape[1] > expected.shape[0])
        masks[page.page] = _mark_mask(diff.diff_regions(expected, scan, frame.ignore), frame.size)
    if sum(int(cv2.countNonZero(mask)) for mask in masks.values()) < 100:
        raise ValueError("No added signature or other visible mark was found.")
    folder.mkdir(parents=True)
    for i, (name, data) in enumerate(files, 1):
        ext = Path(name).suffix.lower() if Path(name).suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg") else ".bin"
        (folder / f"upload_{i}{ext}").write_bytes(data)
    for page, mask in masks.items():
        cv2.imwrite(str(folder / f"page_{page}_marks.png"), mask)
    return registry.approve(folder.name, doc_id, report.version, digest, report.pages_total)


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


def _lines_touched(region, page_lines: list[dict], outline: bool = False) -> dict[int, int]:
    """{line index: changed pixels of this region inside that line's box}, for every line it really touches
    (mask-based, so a diagonal crease's bbox doesn't count). A stamp or stain usually lies across several lines.
    outline=True counts everything inside the mark's outline, within the margin OCR crops with: a stamp's ring or a
    stain's rim garbles the text it surrounds without putting ink of its own on every line."""
    rx, ry, rw, rh = region.bbox
    mask, m = region.mask, 0
    if outline:
        mask, m = np.zeros_like(region.mask), lines.ZONE_MARGIN
        cv2.fillConvexPoly(mask, cv2.convexHull(cv2.findNonZero(region.mask)), 255)
    out = {}
    for i, line in enumerate(page_lines):
        x, y, w, h = line["bbox"]
        x0, y0, x1, y1 = max(rx, x - m), max(ry, y - m), min(rx + rw, x + w + m), min(ry + rh, y + h + m)
        if x1 <= x0 or y1 <= y0:
            continue
        px = int(np.count_nonzero(mask[y0 - ry:y1 - ry, x0 - rx:x1 - rx]))
        if px >= MIN_LINE_PIXELS:
            out[i] = px
    return out


def _codes(image: np.ndarray, frame) -> dict[str, list[int]]:
    """{text: bbox} of every QR code or 2D barcode on the page except the seal. A swapped payment code is content."""
    page = image.copy()
    x, y, w, h = frame.qr
    page[y - 6:y + h + 6, x - 6:x + w + 6] = 255
    out = {}
    for r in zxingcpp.read_barcodes(page, formats=zxingcpp.BarcodeFormat.AllMatrix):  # 2D only: linear symbologies misfire on ruled text
        p = r.position
        xs, ys = zip(*[(q.x, q.y) for q in (p.top_left, p.top_right, p.bottom_right, p.bottom_left)])
        out[r.text] = [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))]
    return out


def _letters(text: str) -> str:
    return "".join(c for c in text if c.isalnum())


def _added_text(scan: np.ndarray, region) -> float:
    """OCR confidence if the ink this region added reads as printed text, else 0. Only the changed pixels are read
    (everything else is painted white), so genuine text next to the region can't be mistaken for an addition."""
    if region.added < 0.5:
        return 0.0
    x, y, w, h = region.bbox
    if min(w, h) < 16 or max(w, h) > 100 * min(w, h):  # RapidOCR cannot resize a thin sliver to a valid image.
        return 0.0
    crop = lines.ink_only(scan[y:y + h, x:x + w])
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    crop[gray > 0.55 * np.percentile(gray, 90)] = 255  # printed text is dark: the pale fringe ink_only leaves of a stamp's lettering is not
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
        return "MODIFIED", HEADLINES["code" if change.id.startswith("code") else "added" if change.line is None else "altered"]
    if not aligned or unreadable:
        return "INCONCLUSIVE", HEADLINES["unread"]
    if any(x.severity != "info" or (x.type != "unknown" and x.confidence >= NOTE_CONF) for x in findings):
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

    approved = registry.find_approval(_files_digest(files))
    if approved:
        entry = registry.get(approved["doc_id"], approved["version"])
        known(entry)
        report.approval_id = approved["id"]
        report.mode, report.pages_checked = "approved", list(range(1, approved["pages"] + 1))
        report.verdict, report.headline = _decide(entry["status"], entry["current_version"], True, [], 0, [])
        if report.verdict == "AUTHENTIC":
            report.verdict, report.headline = "AUTHENTIC_WITH_NOTES", HEADLINES["approved_exact"]
        timings["total"] = round((time.perf_counter() - start) * 1000, 1)
        report.timings = timings
        return report

    images = _load(files)
    lap("load")
    out = data_dir() / "reports" / rid
    out.mkdir(parents=True)
    trusted = seal.load_trusted_keys()
    sealed: list[tuple[PageReport, seal.SealData]] = []  # pages whose seal is in the registry
    observed_marks: dict[int, np.ndarray] = {}

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
        if aligned.method == "qr":
            page.verdict, page.headline = _decide(entry["status"], entry["current_version"], False, [], 0, [])
            if page.verdict == "INCONCLUSIVE":
                page.headline = HEADLINES["qr_only"]
            save("scan", scan)
            continue
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
        observed_marks[d.page] = _mark_mask(regions, frame.size)
        lap("diff")
        ela = cv2.warpPerspective(forensics.ela(image), aligned.H, (scan.shape[1], scan.shape[0]))
        lap("forensics")

        boxes = [ln["bbox"] for ln in page_lines]
        covered: dict[int, str] = {}  # line index -> the kind of mark lying on it
        for n, region in enumerate(regions, 1):
            kind, conf = classify.classify(classify.extract_features(scan, expected, region, boxes, ela))
            touched = _lines_touched(region, page_lines)
            line = max(touched, key=touched.get, default=None)
            if line is None and (read_conf := _added_text(scan, region)):  # the whole page is protected, not just its lines
                kind, conf = "text_change", max(float(conf), read_conf)
            if conf < NOTE_CONF:  # a guess we wouldn't act on isn't reported as a fact
                kind = "unknown"
            if kind not in ("text_change", "unknown"):
                covered.update(dict.fromkeys(_lines_touched(region, page_lines, outline=True), kind))
            rx, ry, rw, rh = region.bbox
            cx, cy, cw, ch = frame.content
            big = (kind == "unknown" and region.added >= 0.5 and region.area >= BIG_MARK_PIXELS
                   and rx >= cx and ry >= cy and rx + rw <= cx + cw and ry + rh <= cy + ch)  # capture noise hugs the page edges
            where = "on a printed line" if line is not None else "outside the printed text"
            severity = "critical" if kind == "text_change" else "warning" if big or (line is not None and kind != "unknown") else "info"
            bbox = [int(v) for v in region.bbox]
            if severity == "critical" and line is not None:  # frame the whole line, one finding per line: keep the more confident
                bbox = page_lines[line]["bbox"]
                same = next((x for x in page.findings if x.severity == "critical" and x.line == line), None)
                if same is not None:
                    if same.confidence >= conf:
                        continue
                    page.findings.remove(same)
            message = ("Something was added here that isn't in the issued document." if big else
                       "Printed text was added here." if kind == "text_change" and line is None else MESSAGES[kind].format(where=where))
            page.findings.append(Finding(id=f"f{n}", type=kind, bbox=bbox, line=line, severity=severity,
                                         confidence=round(float(conf), 2), message=message))
        known_codes = _codes(expected, frame)
        for n, (text, box) in enumerate(_codes(scan, frame).items(), 1):
            if text not in known_codes:
                page.findings.append(Finding(id=f"code{n}", type="text_change", bbox=box, severity="critical", confidence=1.0,
                                             message="This QR code or barcode isn't in the issued document."))
        lap("classify")

        for i, r in results.items():  # a mark lying on a line makes a differing read unreliable: junk characters are damage, not an edit
            if r.status == "MISMATCH" and i in covered:
                r.status = "UNREADABLE"
                page.notes.append(f"Something covers a line ({covered[i].replace('_', ' ')}), so its text couldn't be read reliably.")
        for i, r in results.items():  # every MISMATCH line is highlighted, whether or not the visual diff caught it
            if r.status == "MISMATCH" and not any(x.line == i and x.type == "text_change" for x in page.findings):
                page.findings.append(Finding(id=f"m{i}", type="text_change", bbox=r.bbox, line=i, severity="critical", confidence=r.confidence,
                                             message=f'This line reads "{r.read}", which is not what was issued.'))
        severity_rank = {"critical": 0, "warning": 1, "info": 2}
        page.findings.sort(key=lambda x: (severity_rank[x.severity], x.type == "unknown", -x.confidence))
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
    # An approval only ever covers the marks staff looked at: it must never upgrade a page that failed on its own.
    if (report.registry_status == "active" and report.verdict in ("AUTHENTIC", "AUTHENTIC_WITH_NOTES")
            and sorted(p.page for p in report.pages if p.page is not None) == list(range(1, report.pages_total + 1))):
        for approval in registry.approvals(report.doc_id, report.version):
            folder = data_dir() / "approved" / approval["id"]
            masks = {p: cv2.imread(str(folder / f"page_{p}_marks.png"), cv2.IMREAD_GRAYSCALE)
                     for p in report.pages_checked}
            if all(masks[p] is not None and p in observed_marks and _same_marks(masks[p], observed_marks[p])
                   for p in report.pages_checked):
                report.approval_id = approval["id"]
                report.verdict, report.headline = "AUTHENTIC_WITH_NOTES", HEADLINES["approved_scan"]
                for page in report.pages:
                    page.verdict, page.headline = "AUTHENTIC_WITH_NOTES", HEADLINES["approved_scan"]
                break
    timings["total"] = round((time.perf_counter() - start) * 1000, 1)
    report.timings = timings
    return report
