# Signet

Signet issues school certificates with a cryptographic seal and verifies photos or scans of them fully offline. It reports what changed, where, and whether it matters; a person decides intent.

"We don't accuse, we explain."

## Requirements

- Python 3.11 or 3.12
- No system binaries (no Tesseract, zbar or poppler); pip only, CPU only
- Internet once, for the first install. After that it works with Wi-Fi off

## Quick start

**macOS / Linux:**
```bash
./run.sh
```

**Windows:**
```cmd
run.bat
```

The first run creates `.venv`, installs dependencies, trains the change classifier (about 100 seconds on a MacBook Air M4), and builds the demo set into `demo/`. Later runs skip this and start in seconds, even without internet.

Open http://localhost:8000 in your browser. The script also prints a LAN URL for phones on the same network.

**From a phone on the same network:** open the LAN URL and tap "Take photo" to use the phone camera. (The "Use webcam" button appears only on `localhost`, because browsers allow live camera access only on secure origins.)

`run.bat` mirrors `run.sh` but was written on macOS and has not been run on a real Windows machine yet.

**To use a different port:** `PORT=9000 ./run.sh`

## What you can do

- **Issue:** Fill in six fields and get a certificate (PNG and PDF) with a signed QR seal and four alignment markers. The signing key is created on first run and stays in `keys/` on this machine.
- **Verify:** Upload or photograph a certificate (PNG, JPG or PDF). You get a verdict, a field-by-field comparison, and the page with every change boxed and explained in plain language.
- **Registry:** List all issued certificates, revoke one, or reissue with corrected fields. The old version shows as revoked and points to the new one.

## How verification works

1. **Load the image.** PDF first pages are rendered at 200 DPI; images larger than 3000 px on the long side are scaled down.
2. **Decode the QR.** If no QR code is found, only forensics run (error-level map and copy-move detection) and the verdict is NO_SEAL.
3. **Verify the seal.** Decode the QR as a SG1 seal, check the Ed25519 signature, and confirm the issuer key is in the trusted list.
4. **Align to markers.** Use up to four ArUco markers at the page corners to correct perspective. If fewer than three are found, use the QR corners instead. If alignment fails, the verdict is INCONCLUSIVE.
5. **Re-render the original.** Given the signed field values, render a clean version of the certificate for comparison.
6. **Read fields and compare.** For each protected zone (name, student ID, grade, program, award, date issued), crop the scanned image, read the text with OCR, and compare to the signed value. Text fields match if similarity is >= 0.90, numeric fields must be exact. Confident reads (>= 0.80) whose letters/digits differ from the sealed value are flagged as MISMATCH even if similarity is high (to catch single-letter edits like "Santos" -> "Santoz").
7. **Visual diff.** Compare the aligned scan against the expected render, ignoring markers and the QR box.
8. **Classify changes.** For each changed region, extract features and run a trained classifier to determine if it is damage, a fold, a stamp, handwriting, a text edit, or unknown noise.
9. **Error-level map.** Compute ELA on the upload and show it as an image layer. (Copy-move detection runs only when there is no seal.)
10. **Decide the verdict.** Apply the rules below.

## Verdicts

| Verdict | Meaning |
|---------|---------|
| AUTHENTIC | Seal verified, every protected field matches, no marked changes. |
| AUTHENTIC_WITH_NOTES | Seal verified and every protected field matches. Stains, folds, stamps or handwriting were found and are listed; the values still read correctly. |
| MISMATCH | A protected field reads differently from the sealed record, or a confident text change overlaps a protected field. |
| INCONCLUSIVE | Seal verified, but one or more fields could not be read clearly enough to compare. Try a sharper photo. |
| REVOKED | The seal is genuine, but the issuer has revoked or superseded this document. |
| INVALID_SEAL | A QR was found, but it is not a valid Signet seal, the signature fails, or the issuer key is not trusted. |
| NO_SEAL | No QR code was found. Forensic analysis (copy-move detection) is shown, but authenticity cannot be confirmed. |

## Architecture

```
browser (web/)
     |
     v
FastAPI app (app/main.py)
     |
     +---> /api/issue, /verify, /registry
     |
     v
core/pipeline.py (orchestration)
     |
     +---> core/qr.py           QR decoding
     +---> core/seal.py          Cryptographic signature verification
     +---> core/align.py         Perspective correction via ArUco markers
     +---> core/template.py      Certificate rendering
     +---> core/ocr.py           Text recognition (ONNX-based)
     +---> core/compare.py       Field value comparison
     +---> core/diff.py          Visual diff (changed regions)
     +---> core/classify.py      ML classifier (change type)
     +---> core/forensics.py     ELA, copy-move detection
     +---> core/registry.py      SQLite: issued certificates, revocations
     |
Data storage:
     keys/                       Issuer private key + trusted public keys
     models/                     Trained classifier (RandomForest)
     runtime/
         issued/                 PNG and PDF of issued certificates
         reports/                Verification report images
         registry.db             SQLite certificate log
```

## Repository layout

```
README.md, DEMO.md              Documentation
CONTRACTS.md                    Interfaces and rules (API, pipeline, seal, verdicts)
DECISIONS.md                    Design decisions and trade-offs
requirements.txt                Python dependencies (pip only, CPU only)
run.sh, run.bat                 Entry points (shell and batch)

app/
  main.py                       FastAPI app, endpoints, lifespan
  schemas.py                    Pydantic models (verdict, field status, findings, report)

core/
  __init__.py                   Paths (ROOT, KEYS_DIR, FONTS_DIR, TEMPLATES_DIR, MODEL_PATH, data_dir, log)
  pipeline.py                   issue() / verify() / reissue() / revoke() orchestration
  qr.py                         QR decoding (symbol quad, corner extraction)
  seal.py                       Ed25519 seal: creation, verification, key management
  registry.py                   SQLite registry of issued certificates and status
  align.py                       Perspective correction (ArUco detection, homography)
  template.py                   Certificate rendering (deterministic, Pillow)
  ocr.py                         Text recognition (RapidOCR, ONNX, warmup)
  compare.py                     Field comparison (normalization, similarity, confidence)
  diff.py                        Visual diff: find changed regions in aligned images
  classify.py                    ML classifier: extract features, predict change type
  forensics.py                   ELA, copy-move detection, heatmap rendering

scripts/
  setup.py                       Check fonts, create the issuer key and data folders, warm up OCR
  train_classifier.py            Train RandomForest on synthetic tampering data
  make_demo_set.py              Build 10 demo files + expected.json into demo/

devtools/
  demo_set.py                    Demo builder: issue, tamper, simulate photos, check
  tamper.py                      Simulate changes: stamp, scribble, stain, fold, retype
  photo_sim.py                   Simulate printed-and-photographed: warp, lighting, JPEG

web/
  index.html                     Single-page app
  app.js                         Issue, verify, registry, report display
  styles.css                     Styling
  mock_report.json               Static demo data for UI testing

templates/
  cert-v1.json                   A4 landscape template: fields, markers, zones, decorative text

assets/
  fonts/                         DejaVu fonts (committed, not downloaded)

tests/
  test_<module>.py               Unit tests per core module
  test_acceptance.py             End-to-end: all 10 demo files must pass
  test_offline.py                Proof that no network is accessed
  conftest.py                    pytest fixtures, tmp data_dir per test

.gitignore                       Ignore .venv, runtime/, keys/, models/, demo/ (generated)
```

## Tests

**Run all 102 tests** (about 45 seconds):
```bash
.venv/bin/python -m pytest tests -q
```

**Acceptance: 10 demo files** (run with `-s` to see the table):
```bash
.venv/bin/python -m pytest tests/test_acceptance.py -q -s
```

Expected results (M4 MacBook Air, models warm):
```
file                         expected               actual                 ms
01_genuine.png               AUTHENTIC              AUTHENTIC              614
02_genuine_photo.jpg         AUTHENTIC              AUTHENTIC              605
03_stained_folded.jpg        AUTHENTIC_WITH_NOTES   AUTHENTIC_WITH_NOTES   746
04_stamped_annotated.jpg     AUTHENTIC_WITH_NOTES   AUTHENTIC_WITH_NOTES   842
05_grade_edited.png          MISMATCH               MISMATCH               657
06_name_edited_photo.jpg     MISMATCH               MISMATCH               726
07_revoked.png               REVOKED                REVOKED                668
08_untrusted_seal.png        INVALID_SEAL           INVALID_SEAL           122
09_smudged_field.jpg         INCONCLUSIVE           INCONCLUSIVE           1433
10_no_seal_edited.jpg        NO_SEAL                NO_SEAL                966
```

**Offline proof:**
```bash
.venv/bin/python -m pytest tests/test_offline.py -q
```

This test blocks all sockets, then runs a full issue -> verify -> revoke cycle. It also checks that the UI has no external URLs (except SVG namespace strings, which are never fetched).

## Proving it is offline

1. **Wi-Fi test:** turn off Wi-Fi and verify a file. It still works.
2. **Socket blocking test:** `tests/test_offline.py` replaces `socket.socket` with a function that raises, then runs a full issue -> verify -> revoke cycle.
3. **Source inspection:** `grep -rnE "https?://" web/` finds only an SVG namespace string, never actual URLs.
4. **Model packaging:** OCR models (PP-OCRv6 ONNX) are shipped inside the installed pip wheel. Nothing is downloaded at runtime.
5. **FastAPI docs disabled:** the `/docs` page (which loads Swagger assets from a CDN) is disabled.

## Limits

- **Demo photos are simulated:** perspective, lighting, noise, blur, JPEG artifacts. Real phone photos of printed certificates have not been tested yet.
- **One template:** cert-v1 only (A4 landscape, 200 DPI, six protected fields, four markers).
- **Classifier training data:** trained on about 350 synthetic regions (stamp, handwriting, stain/damage, fold, text edit). Held-out accuracy is 0.94-0.96 on synthetic data. Real-world accuracy not yet measured.
- **Copy-move detection:** requires a copied block roughly 85 px tall or 300 px wide or larger.
- **ELA visualization:** shown as an image layer but not converted to findings (single-compression JPEG lights up every text edge, creating false positives).
- **QR positioning:** marks drawn inside the QR box or over an alignment marker are not reported (those areas are ignored by the visual diff).
- **Issuer key storage:** stored unencrypted in `keys/` (suitable for a lab or school; not for internet-facing production).
- **Report retention:** reports accumulate under `runtime/reports/` and are never cleaned up (fine for a demo; add a retention sweep before deployment).
- **Windows batch script:** written on macOS and not yet run on a real Windows machine.

---

See **DEMO.md** for a presentation walkthrough, **CONTRACTS.md** for API and pipeline details, and **DECISIONS.md** for design rationale.
