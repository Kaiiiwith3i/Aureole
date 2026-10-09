# Signet

Signet seals documents and checks whether a submitted file or page image matches what this installation issued. Staff can issue, reissue and revoke documents; anyone can verify them. The verifier reports observable differences and leaves intent to a person.

## Run

Python 3.11 or 3.12 is required. On macOS/Linux run `./run.sh`; on Windows run `run.bat`. The first run installs the Python requirements, trains the local change classifier and builds ten demo files. Later runs reuse those artifacts. Open `http://localhost:8000` (or set `PORT=9000`). The staff password is `SIGNET_STAFF_PASSWORD` when set; otherwise it is generated once in `keys/staff_password.txt` with owner-only permissions.

TXT and PDF work without other software. DOCX, XLS and XLSX conversion needs LibreOffice (`soffice` on PATH or `SIGNET_SOFFICE=/path/to/soffice`). The app is local and works offline after installation; it uses RapidOCR and a local RandomForest, with no cloud AI. This server listens on the local network by default. Set `SIGNET_DATA_DIR` to put mutable data in a different directory. V2 uses `runtime/registry-v2.db`; an older `runtime/registry.db` is left untouched.

## Use

1. Sign in on **Issue** and upload a TXT, DOCX, PDF, XLS or XLSX document (up to 10 pages and 25 MB). Download the framed PDF. Its text remains selectable when the source has text.
2. On **Verify**, upload that PDF, an edited or re-saved PDF, or page photos/scans. An exact byte match is reported as digital verification; all other inputs are checked page by page against the registry's copy. Upload every page for a complete result.
3. On **Registry**, staff can download, reissue or revoke a document. Earlier versions become superseded and verify as revoked.
4. To accept a signature added after issue, staff choose **Review signed copy** on the active registry entry and upload a scanned PDF or all page photos. Signet checks the printed content first. Staff review the result and approve the added mark. The unsigned issued file stays valid; later scans only show staff approval when their added ink closely matches the approved copy.

A public verification report hides the issued text and original image. A signed QR alone is never treated as proof that the visible page matches. See [CONTRACTS.md](CONTRACTS.md) for seal, registry, verdict and API rules.

## Checks

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/make_demo_set.py
.venv/bin/python scripts/train_classifier.py
```

The demo builder records its documents in the current `SIGNET_DATA_DIR`. The classifier's holdout score comes from synthetic pages only; real photo accuracy still needs measurement. See [DEMO.md](DEMO.md) for the ten demo cases.

## Known limits

- TXT-origin issued PDFs are roughly 450 KB per page because PDFium embeds the font on each page.
- OCR and visual classification can be inconclusive on obscured text. A mark over a line can turn a differing read into `INCONCLUSIVE`.
- If corner markers are hidden, QR-only alignment is reported as inconclusive because it can drift far from the QR. Submit a full-page photo with visible corners.
- Matching a handwritten mark to an approved scan does not prove the signer's identity. Staff remain responsible for deciding whether to approve the signature; unclear recaptures retain the ordinary comparison result.
- The Windows launcher has not been exercised on a Windows machine.
