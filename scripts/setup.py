"""One-time local setup: fonts, issuer key, data dirs, OCR warm-up. Idempotent, no network."""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FONTS = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"]


def fonts() -> str:
    from core import FONTS_DIR
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    missing = [f for f in FONTS if not (FONTS_DIR / f).exists()]
    if missing:
        try:
            import matplotlib
            src = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        except ImportError:
            raise RuntimeError(f"missing fonts {missing} in {FONTS_DIR} and matplotlib is not installed; copy DejaVu TTFs there")
        for f in missing:
            if not (src / f).exists():
                raise RuntimeError(f"font {f} not found in {FONTS_DIR} or {src}")
            shutil.copy(src / f, FONTS_DIR / f)
    return f"{len(FONTS)} fonts in {FONTS_DIR}" + (f" (copied {len(missing)})" if missing else "")


def keys() -> str:
    from core import seal
    return f"issuer key ready, kid {seal.load_or_create_issuer_key()[1]}"


def data() -> str:
    from core import data_dir
    d = data_dir()
    for sub in ("issued", "reports"):
        (d / sub).mkdir(exist_ok=True)
    return f"data dir {d}"


def ocr() -> str:
    from core import ocr as o
    t0 = time.perf_counter()
    o.warm_up()
    return f"OCR engine {o.engine_name()} warm in {time.perf_counter() - t0:.1f}s"


def main() -> int:
    for name, step in (("fonts", fonts), ("keys", keys), ("data", data), ("ocr", ocr)):
        try:
            print(f"[ok] {name}: {step()}")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
