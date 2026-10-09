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
