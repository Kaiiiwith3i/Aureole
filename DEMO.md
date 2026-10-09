# Signet demo

Run `./run.sh` once, then open the printed local URL. The launcher builds `demo/` and registers its sample documents in the active v2 registry. All names and organisations in the samples are fictional.

| File | Expected result | What it shows |
|---|---|---|
| `01_genuine.png` | AUTHENTIC | Clean rendered page |
| `02_genuine_photo.jpg` | AUTHENTIC | Photo perspective, lighting and JPEG compression |
| `03_stained_folded.jpg` | AUTHENTIC_WITH_NOTES | Physical wear without a text change |
| `04_stamped_annotated.jpg` | AUTHENTIC_WITH_NOTES | Extra stamp and handwriting |
| `05_salary_edited.png` | MODIFIED | One digit changed on a printed line |
| `06_name_edited_photo.jpg` | MODIFIED | Name changed, then photographed |
| `07_superseded.png` | REVOKED | Valid older version replaced by v2 |
| `08_untrusted_seal.png` | INVALID_SEAL | QR signed by an untrusted key |
| `09_smudged_line.jpg` | INCONCLUSIVE | Printed line no longer readable |
| `10_unsealed.png` | NOT_ISSUED | Document without the Signet frame |

Try the issued PDF from the Registry for exact digital verification, then upload its rendered page to see page comparison. Sign out and verify again to see the public report without the issued original or expected line text.

These files exercise the application; they are synthetic, not evidence of accuracy on real phones, printers or damaged paper. Document-specific rules and verdict precedence are in [CONTRACTS.md](CONTRACTS.md).
