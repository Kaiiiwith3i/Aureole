# Decisions

Calls made without asking, newest last.

1. **Agents.** `.claude/agents/` was empty, so the three agent definitions (module-builder = Sonnet, qa-verifier = Sonnet, chore-runner = Haiku) were written here. "Haiku 5.5" doesn't exist; `haiku` resolves to the current Haiku.
2. **Python 3.11.15** (3.12 isn't installed on this machine).
3. **OCR = `rapidocr` 3.10** (PP-OCRv6 small det/rec, ONNX). Its models ship inside the wheel, so nothing is downloaded at runtime. It pulls `opencv-python-headless` 5.0, the only OpenCV wheel installed; `cv2.aruco.ArucoDetector` is present.
4. **Fonts are committed** in `assets/fonts/` (DejaVu, extracted once from the matplotlib wheel, licence alongside) instead of copied at setup. matplotlib is therefore not a dependency. `scripts/setup.py` only verifies they exist.
5. **QR box is 540 px, not 480**, with a 2-module quiet zone inside the box. A realistic seal is ~330-380 bytes = QR version 18-20 at level H; 480 px would give < 5 px/module. The page around the box is white, which completes the quiet zone.
6. **Field length caps** (name 60, student_id 20, program 60, award 40, grade 8) keep every seal within version 20 (H, or Q as fallback).
7. **Diacritics are stripped during comparison** (ñ -> n on both sides). The OCR model is weak on accented Latin letters and Filipino names use them; without this a genuine "Peñaflor" could read as a mismatch.
8. **Trusted seal, unknown to the local registry** -> verified normally with `registry_status: "unknown"` and a note. The signature already proves the issuer; the registry only adds revocation.
9. **A non-Signet QR code** on a document counts as `INVALID_SEAL` (a QR was found, it isn't a trusted seal).
10. **NO_SEAL findings use input-image pixel coordinates** (there are no markers to align to); `Report.image_size` tells the UI the coordinate space. Their severity is `warning`.
11. **Report images are JPEG** (q85), not PNG: ~10x faster to write, which matters for the 5 s budget.
12. **Task list lives in `TASKS.md`**: this session has no task-list tool.
13. **Subagents run as `general-purpose` with an explicit `model` override** (Sonnet for builders/QA, Haiku for chores). The session only loads agent definitions at start, so the freshly written `.claude/agents/*` types weren't selectable. The role rules are inlined in each prompt; nothing build-related runs on Opus.
14. **A seal that fails verification stops the analysis** (`INVALID_SEAL` shows the scan only). Its fields can't be trusted, so comparing against them would mislead.
15. **Revoked/superseded documents still get the full analysis**; only the verdict is overridden. One code path, and the report still shows what's on the page.
16. **NO_SEAL findings come from copy-move only.** ELA is shown as a layer but isn't turned into findings: on a single-compression JPEG it lights up every text edge, and thresholding it would report false "modified" regions. Both halves of a copy-move pair are boxed, because the detector can't tell which one is the original.
17. **FastAPI's `/docs` is disabled**: its page loads Swagger assets from a CDN, which would break "zero external URLs".
18. **An undecodable upload is a 400 error**, not a report. Returning `NO_SEAL` for a corrupt file would be a made-up result.
19. **Reports are never cleaned up** (`runtime/reports/` grows by ~1 MB per verification). Fine for a demo; add a retention sweep before any long-running deployment.
20. **One-letter edits are a MISMATCH (near-match guard).** The brief's rule "text fields match at similarity >= 0.90" let "Santos" -> "Santoz" verify as AUTHENTIC: OCR read the altered name correctly and the tolerance waved it through, while the visual diff misses some single-glyph changes. The pipeline now treats a confident reading (>= 0.80) whose letters/digits differ from the sealed value as MISMATCH, provided the same engine reads the clean expected render exactly. Measured: 100/100 genuine verifications (4 people incl. ñ, apostrophes, hyphens; photo strength 1.0-2.0) stayed AUTHENTIC; 6/6 one-letter edits caught as PNG and as photo.
21. **Classifier is trained on ~350 regions, not "a few thousand".** Every training region goes through the real path (render -> tamper -> photo sim -> JPEG -> align -> diff -> features), which costs ~0.7 s per page on this fanless M4 Air even on all cores. 150 pages fits in ~100 s and gives 0.94-0.96 held-out accuracy. The page count is fixed (not a time budget) so the model is identical on every machine. `scripts/train_classifier.py 600` trains a larger model in ~7 minutes.
22. **Marks drawn inside the QR box or over an alignment marker are not reported** (those areas are ignored by the visual diff). The signature already covers the QR content; if the marks break decoding, the result is NO_SEAL or INCONCLUSIVE.
23. **Demo file 08 keeps the genuine document id and shows a better grade**, re-signed with an unknown key: the realistic attack, and the reason the seal has to be checked against trusted keys rather than just decoded.
