# Signet contracts

Source of truth for interfaces. **Function signatures live in the module stubs** (`core/*.py`, `devtools/*.py`) and
the **API shapes live in `app/schemas.py`**; this file holds the rules they share. Don't change a signature: report it.

## What Signet is (v2)
Staff upload any document (TXT, DOCX, PDF, XLS/XLSX). Signet converts it to PDF, frames every page with a signed seal,
and records it in the registry. A document is legitimate **only if this registry has it**. Anyone can submit the issued
file, or a photo/scan of its printed pages, and learn whether it matches what was issued and where it differs.
The six-field `cert-v1` certificate flow is gone.

## Conventions
- Python 3.11, `.venv/bin/python`. Project path may contain spaces: quote it. Run from the repo root.
- Images are `numpy.uint8` **BGR** `(H, W, 3)` unless a docstring says gray. bbox = `[x, y, w, h]` ints, page px.
- Paths: `from core import ROOT, KEYS_DIR, FONTS_DIR, MODEL_PATH, data_dir, log`. Everything mutable goes under `data_dir()` (`SIGNET_DATA_DIR`, default `runtime/`).
- No network in any code path. No `print` in `core/` (use `core.log`). No new pip dependencies (see `requirements.txt`).
- One system dependency, optional: **LibreOffice** (`soffice`), used only to convert DOCX/XLS/XLSX. PDF and TXT work without it.
- Tests: `tests/test_<module>.py`, pytest, run `.venv/bin/python -m pytest tests/test_<module>.py -q`. `tests/conftest.py` points `SIGNET_DATA_DIR` at a tmp dir per test.
- All demo documents, people and organisations are fictional.

## AI
Everything runs on this machine: RapidOCR (ONNX) reads text, a RandomForest classifies changed regions. No language model.
A cloud reader (e.g. Gemini) is **not built**. It may be added later as an opt-in second reader for lines the local OCR
can't read, only if measurements on real photos show the local engines aren't enough. It must never override a digital
hash result, and the app must stay fully working with it off.

## Page frame (`core/layout.py`)
Every issued page is **A4 at 200 DPI**: portrait 1654 x 2339 px, landscape 2339 x 1654 px (source pages of any other size
are scaled to fit). PDF points = px * 0.36. The source page is fitted (aspect kept, centred) into the content box; the
frame around it holds:
- four ArUco `DICT_4X4_50` markers, 84 px, 20 px from the page edges, order TL, TR, BR, BL: ids **0-3 on portrait, 4-7 on landscape** (so the markers alone tell the layout);
- the QR box (234 px) at the right end of the bottom band;
- footer text left of the QR: document id, version, page n of m, fingerprint, issue date.
`layout.layout(landscape)` returns all boxes; nobody hard-codes them.

## Seal string (QR content)
`SG2.<doc>.<ver>.<p>.<n>.<h>.<kid>.<sig>` (ASCII, 8 dot-separated parts).
- `doc` = 8 hex chars; `ver`, `p` (page, 1-based), `n` (page count) = decimal ints >= 1, no leading zeros, `p <= n`;
  `h` = fingerprint = first 16 hex chars of SHA-256 of the **content PDF** (the converted document before framing);
  `kid` = first 8 hex chars of SHA-256(raw public key); `sig` = unpadded base64url Ed25519 signature
  over the UTF-8 bytes of everything before the last dot.
- Keys: `keys/issuer_ed25519.pem` (created on first use), trusted public keys in `keys/trusted/<kid>.pub` (hex of raw key).
- A seal is ~132 chars = QR version 10 at level H. `core.qr.render_qr` is unchanged.
- The seal is a pointer plus a signature. It is never proof by itself: the page is always compared with the registry's copy.

## Registry (`core/registry.py`)
The v2 SQLite file is `data_dir()/registry-v2.db`; a legacy `registry.db` is preserved without migration.
One row per `(doc_id, version)`: `kid, title, source_name, source_type (txt|docx|pdf|xls|xlsx), pages, source_sha256
(the upload), content_sha256 (converted PDF), file_sha256 (issued PDF), status (active|revoked|superseded), issued_at`.
Files per version in `data_dir()/issued/<doc_id>_v<version>/`: `issued.pdf`, `source.<ext>`, `pages.json`.
Staff-approved signed copies are additional records in `approvals` and files under `data_dir()/approved/<approval_id>/`.
They do not replace or supersede the unsigned issued file. Each record links to one document version, keeps the uploaded
scan(s), and stores a page-space mask of approved added ink for later scan comparison.
`pages.json` = `[{"landscape": bool, "lines": [Line, ...]}, ...]`, one item per page.

**Line** = `{"bbox": [x, y, w, h], "text": str, "numeric": bool, "readable": bool}`: one printed line of the issued page
inside the content box. `text` comes from the PDF text layer, or from OCR of the clean render when the page has none.
`numeric` = the text contains no letters. `readable` = at issue time OCR of the clean render read this line back as MATCH;
lines that aren't readable (tiny type, scripts the OCR can't read) are checked by the visual diff only.

## Issuing (`core/pipeline.issue`)
upload -> `convert.to_pdf` (type by content, not by extension) -> `stamp.stamp` -> render each page -> `lines.page_lines`
-> files + registry row. Rejected with `ValueError` (HTTP 422): unsupported type, password-protected file, macro-enabled
OOXML (`vbaProject.bin`), empty document, more than **10 pages**, DOCX/XLS without LibreOffice.
Reissue = same `doc_id`, next version; earlier active versions become `superseded`.

## Signed copies
Anyone holding an issued page may sign it. Staff upload a scanned PDF or all page photos, inspect Signet's comparison,
then explicitly approve the copy. Approval is refused unless every page is present, the seal belongs to an active registry
record, every readable printed line matches, and no text change is found. At least one visible added mark is required.
Staff decide whether that mark is the expected signature; image classification does not establish the signer's identity.
Approval stores the uploaded files and mark masks. The unsigned issued PDF stays active and valid.

## Verification (`core/pipeline.verify`)
Input: 1-10 files (PNG/JPG/PDF), at most 10 pages in total, 25 MB in total.
1. **Digital**: exactly one file whose SHA-256 equals a registry `file_sha256` -> `mode: "digital"`, verdict AUTHENTIC or REVOKED, no page analysis.
2. **Approved copy**: uploaded files byte-identical to a staff-approved signed set -> `mode: "approved"`, `approval_id` set, verdict AUTHENTIC_WITH_NOTES or REVOKED.
3. Otherwise `mode: "pages"`: every PDF page is rendered at 200 DPI, every image is one page (downscaled above 3000 px), and each page goes through:
   `qr.decode_qr` (none: flatten with the markers and retry) -> `seal.verify_seal` -> registry lookup -> `align.align`
   -> expected = `stamp.render_page(issued.pdf, p)` -> per readable Line: OCR the crop (+8 px, coloured ink painted white)
   and `compare.compare_field` -> `diff.diff_regions` (ignoring markers + QR box) -> `classify` -> page verdict.
   A PDF that isn't byte-identical to the issued file (edited, re-saved, scanned) is checked this way, never as "digital".
   If fewer than three markers are visible, QR-only alignment proves the seal but is not precise enough to compare the
   whole page: return `INCONCLUSIVE` (or `REVOKED` for a revoked/superseded record) and request a full-page photo.
   For a complete active document with matching printed lines, page-space added-ink masks are compared to staff-approved
   masks. A close match sets `approval_id` and `AUTHENTIC_WITH_NOTES`; changed text or extra marks are never covered by
   that approval: only a report that is already AUTHENTIC or AUTHENTIC_WITH_NOTES can carry one, and two mask sets match only
   when >= 95% of each lies within 2 px of the other **and** neither has a solid blob (>= 80 px) the other lacks.
   An uncertain mark match remains an ordinary page report without an approval claim.
Budget: < 5 s per page, models warm.

### Line result
- normalize / match / `MISMATCH only when OCR confidence >= 0.80` / near-match guard / ink-only reading: as in `core/compare.py` and v1 (a text line inside the 0.90 tolerance is still MISMATCH when the read is confident, its letters/digits differ, and the engine reads the clean expected crop exactly).
- Covered line: a MISMATCH line touched by a non-text finding (stamp, handwriting, physical_damage, fold; confidence >= 0.6) becomes UNREADABLE. A mark covers **every** line inside its outline (convex hull, plus the 8 px OCR margin), not only the one it is listed under: a stamp's ring garbles text it surrounds without inking it. **Damage must never produce MISMATCH.**
- Lines with `readable: false` are skipped (counted in `lines_unchecked`).
- ponytail: at most 150 lines per page are OCR-checked (largest first); the rest rely on the visual diff, with a note.

### Finding
`{id, type, bbox, line, severity, confidence, message}`. `line` = index into the page's lines, or null.
- type: `stamp | handwriting | physical_damage | fold | text_change | unknown`. A classification below confidence 0.6 is reported as `unknown`: a guess that can't move the verdict isn't shown as a fact.
- **Added text**: a region that touches no line and whose dark ink (coloured and pale pixels painted white, so a stamp's own lettering doesn't count) OCR-reads >= 4 letters/digits at confidence >= 0.80 is `text_change`, whatever the classifier says. On an arbitrary document the whole page is protected, not six zones.
- **Added code**: every QR code or 2D barcode on the scan except the seal is decoded and compared with the issued page's. One that isn't on the issued page (added, or swapped for another) is a `critical` `text_change` at confidence 1.0.
- **Unexplained mark**: an `unknown` region of added ink of >= 1500 px lying wholly inside the content box is a `warning` ("Something was added here..."): the page can't be plain AUTHENTIC.
- severity: `text_change` -> `critical` (so every critical finding decides the verdict); any other known type touching a line, or an unexplained mark -> `warning`; everything else -> `info`.
- Every MISMATCH line gets one `critical` `text_change` finding framing the whole line.
- message: one plain sentence, no accusations ("modified", never "forged"/"fake"/"fraud"). Never quotes the issued text.

### Page verdicts (first rule that applies)
1. `NOT_ISSUED`: no seal QR and no markers on the page. A QR whose text doesn't start with `SG2.` is part of the document (a payment code, a link), not a seal.
2. `INCONCLUSIVE`: markers found but the seal can't be read even after flattening.
3. `INVALID_SEAL`: a QR starting with `SG2.` was found but it isn't well-formed, the signature fails, or `kid` isn't trusted.
4. `NOT_ISSUED`: the signature is valid but the registry has no such `doc`/`ver`, or `h`/`n`/`p` don't match its record. The registry decides.
5. `REVOKED`: registry status `revoked` or `superseded` (`current_version` set when superseded). The page is still analysed.
6. `MODIFIED`: a line is MISMATCH, or a `text_change` finding has confidence >= 0.6.
7. `INCONCLUSIVE`: alignment failed, or a readable line is UNREADABLE.
   QR-only alignment is also `INCONCLUSIVE`; it does not produce line or visual-diff findings.
8. `AUTHENTIC_WITH_NOTES`: every checked line matches and there is >= 1 finding of a known type, or an unexplained mark.
9. `AUTHENTIC`: every checked line matches; `unknown`/low-confidence regions are listed as minor differences.

### Report verdict
- All sealed pages must name the same `doc`/`ver` as the first sealed page; one that doesn't is `MODIFIED` ("belongs to a different issued document").
- Report verdict = the worst page verdict, in this order: INVALID_SEAL, NOT_ISSUED, REVOKED, MODIFIED, INCONCLUSIVE, AUTHENTIC_WITH_NOTES, AUTHENTIC.
- If that is AUTHENTIC or AUTHENTIC_WITH_NOTES but not every page 1..n was provided -> `INCONCLUSIVE` ("pages x of n checked ... pages y were not provided").

Headlines (page level; the report reuses the deciding page's, prefixed `Page p: ` when there are several):
- AUTHENTIC (digital): `This file is identical to the issued document.`
- AUTHENTIC (pages): `Seal verified. No differences from the issued document were found.`
- AUTHENTIC_WITH_NOTES: `Seal verified and the text matches the issued document. We found extra markings on the page.`
  An exact approved upload says it is identical to one staff approved. A later scan says the printed text matches and
  its added marks closely match the approved copy; neither claim identifies the signer.
- MODIFIED: `{k} line(s) on this page don't match the issued document.` / `Text was added to this page that isn't in the issued document.` / `A line on this page looks altered compared with the issued document.` (the visual diff caught it, OCR didn't) / `A QR code or barcode on this page isn't in the issued document.` / more than half the checked lines differ: `The content of this page is different from the document this seal was issued for.`
- INCONCLUSIVE: `Seal verified, but parts of the page couldn't be read clearly enough to confirm them. Try a sharper photo.` / `This looks like a Signet page, but we couldn't read its seal. Try a flatter, sharper photo.`
- REVOKED: `This seal is genuine, but the issuer replaced this document with version {n}.` / `...but the issuer has revoked this document.`
- INVALID_SEAL: `This seal wasn't issued by a trusted issuer.`
- NOT_ISSUED: `No Signet seal was found, so this isn't a document issued by this system.` / `This seal has no matching record in the registry.`

## Access
- **Staff** (one shared login): issue, reissue, revoke, list the registry, download issued files, see the full comparison.
  Password = env `SIGNET_STAFF_PASSWORD`, else generated once into `keys/staff_password.txt` (mode 600).
  Session = random token in an HttpOnly, SameSite=Strict cookie `signet_staff`, kept in memory (a restart logs staff out).
- **Anyone**: verify. A non-staff Report has every `LineResult.expected` and every `images.expected` set to null, and
  `/reports/<id>/<i>_expected.jpg` is refused. The original's content is never shown to someone who only holds a seal.

## API (`app/main.py`, shapes in `app/schemas.py`)
- `POST /api/login` JSON `{password}` -> `{ok}` + cookie; `POST /api/logout` -> `{ok}`; `GET /api/me` -> `{staff: bool}`
- `POST /api/issue` (staff) multipart `file`, optional `title` -> `IssueResponse`
- `POST /api/verify` multipart `files` (repeatable) -> `Report`
- `GET /api/registry` (staff) -> `RegistryEntry[]`; `POST /api/registry/{doc_id}/revoke` (staff) -> `{ok}`; `POST /api/registry/{doc_id}/reissue` (staff) multipart `file`, optional `title` -> `IssueResponse`
- `POST /api/registry/{doc_id}/approve` (staff) multipart repeatable `files` -> `ApprovalResponse`; `GET /api/registry/{doc_id}/approved` (staff) lists approved copies and their file URLs.
- `GET /api/health` -> `Health`
- Static: `/` serves `web/`; `/reports/<report_id>/<i>_{scan,expected,diff,ela}.jpg` (`i` = 1-based position in the upload); `/issued/<doc_id>_v<version>.pdf` (staff).
- `/approved/<approval_id>/upload_<i>.<ext>` serves stored signed scans to staff only.
- Errors: FastAPI default `{"detail": ...}`: 400 unreadable upload, 401 not staff, 404 unknown, 413 too large, 422 can't issue.

## Photo simulation (`devtools/photo_sim.py`), what diff/classify must tolerate
Unchanged from v1: perspective warp (corners moved up to ~4%), dark desk background, lighting gradient (0.75-1.0), warm
tint <= 3%, Gaussian noise sigma ~4, blur sigma ~0.8-1.0, JPEG q75, long side ~2400-3000 px.

## Ownership
| Files | Owner |
|---|---|
| `CONTRACTS.md`, `DECISIONS.md`, `app/*`, `core/__init__.py`, `core/layout.py`, `core/pipeline.py`, `requirements.txt`, `tests/conftest.py`, `tests/test_pipeline.py`, `tests/test_api.py`, `tests/test_acceptance.py`, `tests/test_offline.py` | orchestrator |
| `core/seal.py`, `core/registry.py` + their tests | builder A |
| `core/convert.py`, `core/stamp.py`, `core/align.py`, `core/qr.py`, `scripts/setup.py` + tests | builder B |
| `core/ocr.py`, `core/lines.py`, `core/compare.py` + tests | builder C |
| `core/diff.py`, `core/classify.py`, `core/forensics.py`, `scripts/train_classifier.py` + tests | builder D |
| `web/*` | builder E |
| `devtools/*`, `scripts/make_demo_set.py` + tests | builder F |
| `run.sh`, `run.bat`, `README.md`, `DEMO.md` | chore-runner |
