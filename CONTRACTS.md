# Signet contracts

Source of truth for interfaces. **Function signatures live in the module stubs** (`core/*.py`, `devtools/*.py`) and
the **API shapes live in `app/schemas.py`**; this file holds the rules they share. Don't change a signature: report it.

## Conventions
- Python 3.11, `.venv/bin/python`. Project path contains spaces: quote it. Run from the repo root.
- Images are `numpy.uint8` **BGR** `(H, W, 3)` unless a docstring says gray. bbox = `[x, y, w, h]` ints, template px.
- Paths: `from core import ROOT, KEYS_DIR, FONTS_DIR, TEMPLATES_DIR, MODEL_PATH, data_dir, log`. Everything mutable goes under `data_dir()` (`SIGNET_DATA_DIR`, default `runtime/`).
- No network in any code path. No `print` in `core/` (use `core.log`). No new dependencies (see `requirements.txt`; OpenCV is `opencv-python-headless` 5.x, pulled by rapidocr).
- Tests: `tests/test_<module>.py`, pytest, run `.venv/bin/python -m pytest tests/test_<module>.py -q`. `tests/conftest.py` already points `SIGNET_DATA_DIR` at a tmp dir per test.
- All demo people/schools are fictional; the template footer says "DEMO, not a real credential".

## Template `cert-v1` (`templates/cert-v1.json`)
A4 landscape @ 200 DPI = **2339 x 1654 px**. ArUco `DICT_4X4_50` ids 0 (TL), 1 (TR), 2 (BR), 3 (BL), 90 px, at the listed
top-left `x, y`. QR box `[1630, 950, 540, 540]` (540 rather than 480 so a version-20 seal still gets 5 px/module).
Protected zones: `name`, `student_id`, `grade`, `program`, `award`, `date_issued` (bbox holds only the value; the label is
drawn 50 px above). `numeric: true` for `student_id`, `grade`, `date_issued`. Decorative text/lines/footer are drawn but never OCR-compared.
`free_areas` are blank regions devtools may stamp/scribble on.

## Seal string (QR content)
`SG1.<b64url(payload)>.<b64url(signature)>`, unpadded base64url.
- payload = canonical JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")` of
  `{"kid": "<8 hex>", "doc": "<8-char id>", "ver": 1, "f": {"n": ..., "sid": ..., "prog": ..., "aw": ..., "gr": ..., "dt": "YYYY-MM-DD"}}`
- signature = Ed25519 over the payload bytes. `kid` = first 8 hex chars of SHA-256(raw public key).
- Keys: `keys/issuer_ed25519.pem` (created on first use), trusted public keys in `keys/trusted/<kid>.pub` (hex of raw key).
- QR: lowest version that fits at level **H**; above version 20 drop to **Q** and log; still above 20 -> `ValueError`. Field length caps in `CertFields` keep real input inside this.

## Rendering
`core.template.render_certificate(fields, meta)` is the only renderer, used to issue and to rebuild the expected page from
the signed fields. Deterministic: same input -> identical bytes. `date_issued` is printed exactly as signed (`YYYY-MM-DD`).

## Field result (`core.compare`)
- normalize: NFKC, strip diacritics, casefold, collapse whitespace, no spaces around punctuation; numeric fields also O->0, I/l->1, S->5, B->8.
- match: numeric = exact equality after normalization; text = similarity >= 0.90.
- Near-match guard (`core/pipeline.py`): a text field inside the 0.90 tolerance is still MISMATCH when OCR confidence >= 0.80, its letters/digits differ from the sealed value, and the same engine reads the clean expected render exactly. The tolerance is for OCR noise, not for a one-letter reprint.
- Ink-only reading (`core/pipeline.py`): coloured pixels (stamp ink, ballpoint, stains) are painted white before OCR, because sealed values are printed in black.
- Covered field: if a field would be MISMATCH but a known non-text finding (stamp, handwriting, physical_damage, fold; confidence >= 0.6) lies on its zone, it becomes UNREADABLE with a note. Junk characters from a mark are damage, not an edit.
- Read-back at issue: a certificate is only issued if every field of the fresh render reads back as MATCH (rejects glyphs the font lacks, scripts the OCR can't read, blanks) -> `ValueError` / HTTP 422.
- **MISMATCH only when OCR confidence >= 0.80 and the text doesn't match.** Empty read or lower confidence -> UNREADABLE. Damage must never produce MISMATCH.

## Finding
`{id, type, bbox, field, severity, confidence, message}` (see `app/schemas.py`).
- type: `stamp | handwriting | physical_damage | fold | text_change | digital_edit | unknown`. The classifier emits the first five + `unknown`; `digital_edit` comes only from forensics.
- severity: `text_change` on a protected zone -> `critical`; any other type on a protected zone -> `warning`; elsewhere -> `info`.
- Every MISMATCH field gets a `critical` `text_change` finding on its zone bbox. A critical finding's bbox always covers the whole zone, and there is at most one per field.
- message: one plain sentence, no accusations ("modified", never "forged"/"fake"/"fraud").

## Verdicts (first rule that applies)
1. `INVALID_SEAL`: a QR was found but it is not a valid SG1 seal, the signature fails, or `kid` isn't trusted.
2. `REVOKED`: registry status `revoked` or `superseded` (`current_version` set when superseded).
3. `MISMATCH`: a field is MISMATCH, or a `text_change` finding (confidence >= 0.6) overlaps a protected zone whose field is not UNREADABLE.
4. `INCONCLUSIVE`: alignment failed, or any field is UNREADABLE. Also: the corner markers were found but the seal could not be read even after flattening the page (it is a Signet certificate, so NO_SEAL would be wrong).
5. `AUTHENTIC_WITH_NOTES`: all fields MATCH and >= 1 finding of a known type (not `unknown`) has confidence >= 0.6.
6. `AUTHENTIC`: all fields MATCH; `unknown`/low-confidence regions are listed as minor differences.
7. `NO_SEAL`: no QR found; forensic findings only (`digital_edit`, bbox in input-image px, `image_size` = input size).
A trusted seal whose doc is not in the local registry is verified normally with `registry_status: "unknown"` and a note.

Headlines:
- AUTHENTIC: `Seal verified. Every protected field matches the issuer's record.`
- AUTHENTIC_WITH_NOTES: `Seal verified and every protected field matches. We found extra markings outside the protected areas.`
- MISMATCH: `The printed {field} doesn't match the sealed record: sealed "{a}", printed "{b}".`
- INCONCLUSIVE: `Seal verified, but we couldn't read {field} clearly enough to confirm it. Try a sharper photo.`
- REVOKED: `This seal is genuine, but the issuer replaced this document with version {n}.` (plain revoke: `...but the issuer has revoked this document.`)
- INVALID_SEAL: `This seal wasn't issued by a trusted issuer.`
- NO_SEAL: `No seal found, so authenticity can't be confirmed. Forensic analysis found {k} region(s) that look digitally modified.` / `...found no signs of digital modification.`

## API (`app/main.py`, shapes in `app/schemas.py`)
- `POST /api/issue` JSON `CertFields` -> `IssueResponse`
- `POST /api/verify` multipart `file` (PNG/JPG/PDF) -> `Report`
- `GET /api/registry` -> `RegistryEntry[]`; `POST /api/registry/{doc_id}/revoke` -> `{ok}`; `POST /api/registry/{doc_id}/reissue` JSON `CertFields` -> `IssueResponse`
- `GET /api/health` -> `Health`
- Static: `/` serves `web/` (index.html); `/reports/<report_id>/{scan,expected,diff,ela}.jpg`; `/issued/<doc_id>_v<version>.{png,pdf}`.
- Errors: FastAPI default `{"detail": ...}` with 4xx.
- Report image URLs may be `null` (e.g. no `expected`/`diff` on NO_SEAL). All four images share `image_size`.

## Verification pipeline (`core/pipeline.py`)
load (PDF first page @200 DPI; downscale > 3000 px) -> `qr.decode_qr` (if none: flatten with the markers and retry) -> still none and no markers: forensics only (ELA + copy-move) -> `NO_SEAL`
-> `seal.verify_seal` + registry -> `align.align` (ArUco >= 3 markers, else QR corners) -> `template.render_certificate`
-> per zone `ocr.read_text` on the crop (+8 px margin) and `compare.compare_field` -> `diff.diff_regions` (ignoring markers + QR box)
-> `classify.extract_features` + `classify.classify` -> ELA warped to template space -> verdict -> images -> Report.
Budget: < 5 s per file, models warm.

## Photo simulation (`devtools/photo_sim.py`), what diff/classify must tolerate
Perspective warp (each page corner moved up to ~4% of the page size) onto a dark desk background, multiplicative lighting
gradient (0.75-1.0), warm tint <= 3%, Gaussian noise sigma ~4, blur sigma ~0.8-1.0, saved as JPEG q75. Output long side ~2400-3000 px.

## Ownership
| Files | Owner |
|---|---|
| `CONTRACTS.md`, `DECISIONS.md`, `app/*`, `core/__init__.py`, `core/pipeline.py`, `templates/*`, `requirements.txt`, `tests/conftest.py`, `tests/test_acceptance.py`, `tests/test_offline.py` | orchestrator |
| `core/seal.py`, `core/qr.py`, `core/registry.py` + their tests | builder A |
| `core/template.py`, `core/align.py`, `scripts/setup.py` + tests | builder B |
| `core/ocr.py`, `core/compare.py` + tests | builder C |
| `core/diff.py`, `core/classify.py`, `core/forensics.py` + tests | builder D |
| `web/*` (except `mock_report.json`) | builder E |
| `devtools/*`, `scripts/make_demo_set.py`, `scripts/train_classifier.py` | builder F |
| `run.sh`, `run.bat`, `README.md`, `DEMO.md` | chore-runner |
