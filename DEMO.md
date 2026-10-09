# Signet demo guide

## Before you present

- Run `./run.sh` once **with internet** (first run installs packages, trains the classifier in about 100 seconds and builds `demo/`). After that it starts in seconds with Wi-Fi off.
- Check that `demo/` holds ten files, `01_genuine.png` to `10_no_seal_edited.jpg`.
- Open http://localhost:8000 and set the browser zoom to 125-150% for the projector.
- Keep the `demo/` folder open next to the browser so you can drag files in.
- Verify one file before the audience arrives, so the page and models are warm.

## 3-minute pitch

Each step: **do** the action, **say** the line.

**0:00 Opening**
- Do: show the Verify tab.
- Say: "A certificate photo can be edited in a minute. Signet issues certificates with a cryptographic seal and checks photos or scans of them, entirely on this laptop. We don't accuse, we explain."

**0:15 Turn off Wi-Fi**
- Do: switch Wi-Fi off from the menu bar, in view of the audience.
- Say: "Everything from here on runs with no network. Nothing you upload leaves this machine."

**0:25 File 01, the genuine certificate**
- Do: drag `01_genuine.png` in. Verdict: **AUTHENTIC**.
- Say: "The QR code holds the six protected fields, signed by the school's key. On-device OCR, our first local AI, read each printed field, and every one matches what was sealed." (point at the field table)

**0:50 File 03, stained and folded**
- Do: drag `03_stained_folded.jpg` in. Verdict: **AUTHENTIC, WITH NOTES**.
- Say: "This is a phone photo taken at an angle. Computer vision, our second local AI, found the four corner markers and flattened the page. Our third, a change classifier trained on this laptop, says: that is a coffee stain, that is a fold." (click each finding)
- Say: "Damage is explained, not punished. The values still read correctly, so the document is still authentic."

**1:20 File 04, stamped and annotated**
- Do: drag `04_stamped_annotated.jpg` in. Verdict: **AUTHENTIC, WITH NOTES**.
- Say: "An office stamp and a pen note. The classifier tells them apart and reports that both sit outside the protected areas. A real document picks up marks like these; that shouldn't make it suspect."

**1:40 File 05, the edited grade**
- Do: drag `05_grade_edited.png` in. Verdict: **MISMATCH**. Click the critical finding so the grade is framed in the image.
- Say (read the banner): "The printed general weighted average doesn't match the sealed record: sealed 1.45, printed 1.00."
- Say: "Same font, clean edit, invisible to the eye. The seal still says 1.45, and OCR read 1.00 on the page. We say what changed and where. We don't say who did it or why."

**2:05 File 07, the revoked version**
- Do: drag `07_revoked.png` in. Verdict: **REVOKED**.
- Say: "This seal is genuine. But the registrar found an honest mistake and re-issued the certificate, so this copy has been replaced by version 2. Corrections go through re-issuing, never through editing." (optionally show the Registry tab)

**2:25 File 10, no seal at all**
- Do: drag `10_no_seal_edited.jpg` in. Verdict: **NO SEAL**. Click a finding, then the ELA toggle.
- Say: "No seal, so we can't confirm where this came from, and we say so. Forensics still helps: copy-move detection found two regions of the page that are identical copies of each other."

**2:45 Close**
- Do: turn Wi-Fi back on, or leave it off for questions.
- Say: "Cryptography proves what the school sealed. Three on-device AI components, OCR, a change classifier and computer vision, read the paper and explain the differences. A person makes the final decision. That's Signet."

If you have 20 spare seconds: `08_untrusted_seal.png` (someone re-signed a better grade with their own key: **INVALID SEAL**) and `09_smudged_field.jpg` (student ID smeared: **INCONCLUSIVE**, "try a sharper photo", never a mismatch).

## If something goes wrong

- **Page doesn't load:** the server isn't running. Run `./run.sh` in the project folder.
- **Port 8000 is busy:** `PORT=9000 ./run.sh`, then open http://localhost:9000.
- **A demo file gives an unexpected verdict:** the registry was probably reset. Rebuild with `.venv/bin/python scripts/make_demo_set.py` and use the fresh files in `demo/`.
- **"Use webcam" button is missing:** browsers only allow live camera access on `localhost`. On a phone over the LAN, use "Take photo" instead.

## Likely judge questions

**What if the school made an honest mistake on a certificate?**
The registrar re-issues it with the corrected value. The old copy then verifies as REVOKED and points to the new version (demo file 07). Nobody edits a sealed document.

**What if the paper is damaged?**
If the fields can still be read, the verdict is AUTHENTIC WITH NOTES and the damage is listed. If a field can't be read, the verdict is INCONCLUSIVE and we ask for a sharper photo. Damage never produces MISMATCH: that verdict needs a confident reading that differs from the seal.

**Why both cryptography and AI?**
The signature proves what the issuer sealed and can't be edited or guessed. But a signature can't read paper. The AI reads what is actually printed and explains how it differs. Either one alone leaves a gap.

**Is any data sent anywhere?**
No. The app makes no outbound connections. You can check: it works with Wi-Fi off, `tests/test_offline.py` blocks all sockets and still runs a full issue and verify, the OCR models ship inside the installed package, and the UI loads no external files.

**Can someone copy the QR code onto another document?**
They can, but the seal contains the signed field values. If the printed fields differ, the verdict is MISMATCH. If they are identical, it is simply a copy of the same genuine certificate.

**What if someone generates their own QR code?**
The signature is checked against the school's trusted public keys. A seal signed by any other key is INVALID SEAL. Demo file 08 is exactly that: the genuine document id, a better grade, re-signed with an unknown key.

**How accurate is the classifier?**
Honest answer: it is trained on about 350 synthetic regions and scores 0.94 to 0.96 on held-out synthetic data. In our sweeps, damage was never reported as a mismatch. Accuracy on real-world marks has not been measured yet. The classifier only labels marks; MISMATCH comes from the seal and the reading, not from the classifier guessing.

**Does it work on real phone photos?**
It is built for them: marker alignment, lighting normalization, tolerance for blur and JPEG. So far it has been tested on simulated photos (perspective, lighting, noise, blur, compression). Testing with printed certificates photographed by real phones is the next step.

**What about documents without a seal?**
The verdict is NO SEAL. We can't confirm authenticity and we say so. We still run copy-move detection and show an error-level map, and report any regions that look digitally modified.

**What stops someone stealing the signing key?**
In this prototype the key is a file on the issuing laptop. A real deployment would keep it in a hardware token or key service. Verification only ever needs the public key.

---

More detail: `README.md` (setup, architecture, limits), `CONTRACTS.md` (rules and API), `DECISIONS.md` (trade-offs).
