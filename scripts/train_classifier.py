"""Train the change-region classifier on synthetic tampering: .venv/bin/python scripts/train_classifier.py [pages [budget_seconds]]

Each page = render_certificate -> 3-8 non-touching tampers at random places (over protected zones too, so zone_overlap is no shortcut
for text_change) -> digital or phone photo -> the pipeline's own align -> diff -> features. A region is labelled by the
tamper whose changed pixels it mostly covers; regions touching no tamper (capture noise) are "unknown"."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import joblib  # noqa: E402
import numpy as np  # noqa: E402
from joblib import Parallel, delayed  # noqa: E402

import core  # noqa: E402
from core import align, diff, forensics, template  # noqa: E402
from core.classify import FEATURE_NAMES, LABELS, extract_features  # noqa: E402
from devtools import tamper  # noqa: E402
from devtools.photo_sim import simulate_photo  # noqa: E402

PAGES = 150  # ~350 regions in ~100 s on a fanless M4 Air. Fixed count, so the model is the same on every machine.
BUDGET = 10_000  # seconds; optional cut-off (2nd CLI arg). Off by default: a time cut-off would make the model depend on machine load.
NAMES = ["Maria Clara Santos", "Jose Rivera", "Ana Marie Dela Cruz", "Paolo Gabriel Reyes", "Liza Mae Fernandez", "Ramon Bautista"]
PROGRAMS = ["BS Computer Science", "BS Information Technology", "BS Accountancy", "BA Communication"]
AWARDS = ["Dean's Lister", "Cum Laude", "Certificate of Completion", "Best Thesis"]
KINDS = ["stamp", "handwriting", "physical_damage", "fold", "text_change", "smudge"]


def _fields(rng) -> dict:
    return {"name": str(rng.choice(NAMES)), "student_id": f"20{rng.integers(15, 27)}-{rng.integers(0, 99999):05d}",
            "grade": f"{rng.integers(1, 4)}.{rng.choice(['00', '25', '50', '75'])}", "program": str(rng.choice(PROGRAMS)),
            "award": str(rng.choice(AWARDS)), "date_issued": f"20{rng.integers(20, 27)}-{rng.integers(1, 13):02d}-{rng.integers(1, 29):02d}"}


def _altered(value: str, rng) -> str:
    """A different value of the same shape: one digit/letter changed, or a different word."""
    chars = list(value)
    idx = [i for i, c in enumerate(chars) if c.isalnum()]
    for i in rng.choice(idx, size=min(len(idx), int(rng.integers(1, 3))), replace=False):
        chars[i] = str(rng.integers(0, 10)) if chars[i].isdigit() else chr(int(rng.integers(97, 123)))
    return "".join(chars)


def _apply(page, kind, rng, zs, fields):
    """-> (new page, label, bbox). Positions are uniform over the page, so about a fifth land on protected zones by chance;
    half of the stamp/scribble/stain/fold placements are forced onto a zone."""
    H, W = page.shape[:2]
    seed = int(rng.integers(1 << 30))
    on_zone = rng.random() < 0.5
    zx, zy, zw, zh = zs[str(rng.choice(list(zs)))]["bbox"]
    cx, cy = (int(rng.integers(zx, zx + zw)), int(rng.integers(zy, zy + zh))) if on_zone else (int(rng.integers(150, W - 150)), int(rng.integers(150, H - 150)))
    if kind == "stamp":
        return _tag(tamper.add_stamp(page, (cx, cy), int(rng.integers(70, 150)), seed=seed), "stamp")
    if kind == "handwriting":
        w, h = int(rng.integers(200, 700)), int(rng.integers(70, 170))
        return _tag(tamper.add_scribble(page, [min(max(cx - w // 2, 150), W - 150 - w), min(max(cy - h // 2, 150), H - 150 - h), w, h], seed=seed), "handwriting")
    if kind == "physical_damage":
        return _tag(tamper.add_stain(page, (cx, cy), int(rng.integers(70, 230)), seed=seed), "physical_damage")
    if kind == "fold":
        vertical = bool(rng.random() < 0.6)
        pos = (cx / W if vertical else cy / H) if on_zone else rng.uniform(0.1, 0.9)
        return _tag(tamper.add_fold(page, float(np.clip(pos, 0.08, 0.92)), vertical, seed=seed), "fold")
    key = str(rng.choice(list(zs)))
    if kind == "smudge":
        return _tag(tamper.smudge_field(page, key, seed=seed), "physical_damage")
    return _tag(tamper.retype_field(page, key, _altered(fields[key], rng) if rng.random() < 0.6 else _fields(rng)[key]), "text_change")


def _tag(result, label):
    return result[0], label, result[1]


def make_page(i: int, deadline: float):
    """Feature rows + labels for one synthetic page (runs in a worker process)."""
    if time.time() > deadline:
        return [], []
    cv2.setNumThreads(1)
    rng = np.random.default_rng(1000 + i)
    zs, tpl = template.zones(), template.load_template()
    fields = _fields(rng)
    page = template.render_certificate(fields, {"seal": None, "doc_id": "train0001", "version": 1})  # no QR: it is ignored anyway
    mode = rng.choice(["clean_photo", "photo", "digital"], p=[0.3, 0.55, 0.15])
    labelled = []  # (label, footprint mask)
    scan = page
    if mode != "clean_photo":
        used = []  # bboxes of placed tampers: a new one must not touch them, so regions stay one-label (a fold may cross anything)
        for j, kind in enumerate(rng.choice(KINDS, size=int(rng.integers(3, 9)))):
            new, label, (bx, by, bw, bh) = _apply(scan, str(kind), rng, zs, fields)
            if label != "fold" and any(bx < ux + uw + 40 and ux < bx + bw + 40 and by < uy + uh + 40 and uy < by + bh + 40 for ux, uy, uw, uh in used):
                continue
            if label == "fold" and any(lb == "fold" for lb, _ in labelled):
                continue
            used += [] if label == "fold" else [(bx, by, bw, bh)]
            fp = cv2.dilate((cv2.absdiff(new, scan).max(2) > 10).astype(np.uint8), np.ones((15, 15), np.uint8))
            labelled.append((label, fp))
            scan = new
    if mode != "digital":
        hard = mode == "clean_photo"  # clean pages get rougher captures: the noise class must cover more than the demo's photos
        photo = simulate_photo(scan, seed=int(rng.integers(1 << 30)), strength=float(rng.uniform(1.2, 2.6) if hard else rng.uniform(0.7, 1.3)))
        scan = cv2.imdecode(cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(45, 71)) if hard else 75])[1], cv2.IMREAD_COLOR)
    res = align.align(scan)
    if res is None:
        return [], []
    sz = tpl["markers"]["size"]
    ignore = [[m["x"] - 12, m["y"] - 12, sz + 24, sz + 24] for m in tpl["markers"]["items"]]
    qx, qy, qw, qh = tpl["qr"]["bbox"]
    ignore.append([qx - 6, qy - 6, qw + 12, qh + 12])
    regions = diff.diff_regions(page, res.image, ignore)
    ela = cv2.warpPerspective(forensics.ela(scan), res.H, (res.image.shape[1], res.image.shape[0]))
    boxes = [z["bbox"] for z in zs.values()]
    X, y = [], []
    for r in regions:
        x0, y0, w, h = r.bbox
        m = r.mask > 0
        counts = {}
        for label, fp in labelled:
            counts[label] = counts.get(label, 0) + int((m & (fp[y0:y0 + h, x0:x0 + w] > 0)).sum())
        label = max(counts, key=counts.get) if counts else "unknown"
        share = counts.get(label, 0) / r.area if counts else 0.0
        if share < 0.02:
            label = "unknown"
        elif share < 0.3:
            continue  # mostly noise with a little tamper in it: ambiguous, leave it out
        X.append(extract_features(res.image, page, r, boxes, ela))
        y.append(LABELS.index(label))
    return X, y


def main() -> None:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split

    t0 = time.time()
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else PAGES
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else BUDGET
    deadline = t0 + budget
    out = Parallel(n_jobs=-1)(delayed(make_page)(i, deadline) for i in range(pages))
    done = sum(1 for xs, _ in out if xs)
    X = np.array([f for xs, _ in out for f in xs], np.float32)
    y = np.array([v for _, ys in out for v in ys])
    print(f"{pages} pages, {done} with change regions -> {len(y)} regions in {time.time() - t0:.0f}s; per class:",
          {LABELS[k]: int((y == k).sum()) for k in range(len(LABELS))})
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=0, stratify=y)
    clf = RandomForestClassifier(n_estimators=300, class_weight="balanced", min_samples_leaf=2, random_state=0, n_jobs=-1).fit(Xtr, ytr)
    pred = clf.predict(Xte)
    print(f"held-out accuracy: {(pred == yte).mean():.3f}")
    labels = list(range(len(LABELS)))
    print(classification_report(yte, pred, labels=labels, target_names=LABELS, zero_division=0))
    print("confusion (rows = true, cols = predicted, order", LABELS, ")\n", confusion_matrix(yte, pred, labels=labels))
    final = RandomForestClassifier(n_estimators=300, class_weight="balanced", min_samples_leaf=2, random_state=0, n_jobs=-1).fit(X, y)
    core.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "features": FEATURE_NAMES, "labels": LABELS}, core.MODEL_PATH)
    print(f"saved {core.MODEL_PATH}; total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
