"""Train the v2 change classifier on synthetic marks on issued document pages."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

import core
from core import align, classify, diff, forensics, layout, pipeline, stamp
from devtools import tamper
from devtools.photo_sim import simulate_photo

TEXTS = [  # three page shapes: dense records, a short letter with blank space, running prose
    "\n".join(f"Record {i:02d}: Employee Avery Stone received payment of PHP {i * 173:,}.00." for i in range(1, 19)),
    "EMPLOYMENT CONFIRMATION\n\nThis confirms that Avery Stone works for Lakeshore Trading Company.\nPosition: Senior Accountant\n"
    "Monthly salary: PHP 48,500.00\nEmployee number: 2021-00482\n\nIssued for reference on 10 October 2026.\n\nRamon Bautista\nHuman Resources Manager\n",
    "\n\n".join("The supplier shall deliver the goods listed in Schedule A within thirty days of this order, and the buyer shall "
                "pay the agreed price of PHP 125,400.00 within fifteen days of delivery." for _ in range(6)),
]
ADDED = ["Approved loan: PHP 950,000.00", "PHP 75,000", "Paid in full 2026-10-10", "and all related rights", "Total 12,450.00", "Blake Rivera"]
KINDS = ("stamp", "handwriting", "physical_damage", "fold", "text_change", "unknown")
REPEATS = 40  # scenes per kind; ~3 min on a MacBook Air M4. Fixed, so the model is the same on every machine.


def _scene(kind: str, page: np.ndarray, lines: list[dict], frame, rng):
    """(tampered page, bbox of the mark). Sizes and positions vary, on printed lines and on blank paper alike."""
    cx, cy, cw, ch = frame.content
    line = lines[int(rng.integers(len(lines)))]
    lx, ly, lw, lh = line["bbox"]
    on_line = rng.random() < 0.5
    at = (lx + int(rng.integers(0, max(lw, 1))), ly + lh // 2) if on_line else (cx + int(rng.integers(150, cw - 150)), cy + int(rng.integers(150, ch - 150)))
    if kind == "stamp":
        return tamper.add_stamp(page, at, int(rng.integers(70, 220)), seed=int(rng.integers(1 << 30)))
    if kind == "handwriting":
        w, h = int(rng.integers(150, 900)), int(rng.integers(50, 200))
        return tamper.add_scribble(page, [min(at[0], cx + cw - w), min(at[1], cy + ch - h), w, h], seed=int(rng.integers(1 << 30)))
    if kind == "physical_damage":
        return tamper.add_stain(page, at, int(rng.integers(60, 200)), seed=int(rng.integers(1 << 30)))
    if kind == "fold":
        return tamper.add_fold(page, float(rng.uniform(0.12, 0.88)), bool(rng.random() < 0.5), seed=int(rng.integers(1 << 30)))
    if kind == "text_change":
        if on_line:  # one character of an issued line retyped
            chars = list(line["text"])
            i = int(rng.choice([k for k, c in enumerate(chars) if c.isalnum()]))
            chars[i] = str((int(chars[i]) + 3) % 10) if chars[i].isdigit() else "z" if chars[i] != "z" else "q"
            return tamper.retype_line(page, line["bbox"], "".join(chars))
        text = ADDED[int(rng.integers(len(ADDED)))]  # printed text added on blank paper
        return tamper.retype_line(page, [min(at[0], cx + cw - 700), at[1], 26 * len(text) // 2, 30], text)
    return page.copy(), [0, 0, 0, 0]  # unknown: nothing was done, whatever differs is capture noise


def samples(repeats: int = REPEATS):
    """Return feature rows and labels from the same framed pages the verifier receives."""
    with tempfile.TemporaryDirectory() as tmp:
        previous = os.environ.get("SIGNET_DATA_DIR")
        os.environ["SIGNET_DATA_DIR"] = tmp
        try:
            frame = layout.layout(False)
            pages = []
            for i, text in enumerate(TEXTS):
                issued = pipeline.issue(text.encode(), f"training-{i}.txt")
                image = stamp.render_page(issued["pdf_path"].read_bytes(), 0)
                pages.append((image, json.loads((issued["pdf_path"].parent / "pages.json").read_text())[0]["lines"]))
            X, y = [], []
            for k, kind in enumerate(KINDS):
                for seed in range(repeats):
                    rng = np.random.default_rng(1000 * k + seed)
                    page, lines = pages[seed % len(pages)]
                    scene, box = _scene(kind, page, lines, frame, rng)
                    if seed % 4:  # three in four are photographed; unmarked pages get rougher photos so there is noise to learn
                        scene = simulate_photo(scene, seed=seed + 200, strength=float(rng.uniform(1.3, 2.2) if kind == "unknown" else rng.uniform(0.8, 1.6)))
                        scene = cv2.imdecode(cv2.imencode(".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, 75])[1], cv2.IMREAD_COLOR)
                    aligned = align.align(scene)
                    if aligned is None:
                        continue
                    ela = cv2.warpPerspective(forensics.ela(scene), aligned.H, frame.size)
                    boxes = [line["bbox"] for line in lines]
                    for region in diff.diff_regions(page, aligned.image, frame.ignore):
                        rx, ry, rw, rh = region.bbox
                        bx, by, bw, bh = box
                        overlap = max(0, min(rx + rw, bx + bw) - max(rx, bx)) * max(0, min(ry + rh, by + bh) - max(ry, by))
                        label = kind if kind != "unknown" and overlap >= 0.2 * rw * rh else "unknown"
                        X.append(classify.extract_features(aligned.image, page, region, boxes, ela))
                        y.append(label)
            return np.asarray(X, np.float32), np.asarray(y)
        finally:
            if previous is None:
                os.environ.pop("SIGNET_DATA_DIR", None)
            else:
                os.environ["SIGNET_DATA_DIR"] = previous


def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else REPEATS
    X, y = samples(repeats)
    counts = {kind: int(np.sum(y == kind)) for kind in KINDS}
    print("Synthetic v2 regions:", counts)
    if min(counts.values()) < 3:
        raise RuntimeError("Not enough examples of every change type; classifier was not replaced.")
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=0, stratify=y)
    check = RandomForestClassifier(n_estimators=100, class_weight="balanced", min_samples_leaf=2, random_state=0, n_jobs=-1).fit(Xtr, ytr)
    print(classification_report(yte, check.predict(Xte), zero_division=0))
    model = RandomForestClassifier(n_estimators=100, class_weight="balanced", min_samples_leaf=2, random_state=0, n_jobs=-1).fit(X, y)
    core.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": classify.FEATURE_NAMES, "labels": classify.LABELS, "training": "v2-issued-pages"}, core.MODEL_PATH)
    print("Saved", core.MODEL_PATH)


if __name__ == "__main__":
    main()
