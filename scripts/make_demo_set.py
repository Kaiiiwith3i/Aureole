"""Write the 10 demo files + expected.json: .venv/bin/python scripts/make_demo_set.py [out_dir]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from devtools.demo_set import build_demo_set  # noqa: E402
from core import ROOT, data_dir  # noqa: E402

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "demo"
    for name, want in build_demo_set(out).items():
        print(f"{name:28} {want['verdict']}")
    if out.resolve() == ROOT / "demo":
        (out / ".v2-built").write_text(str(data_dir().resolve()))
    print(f"written to {out}")
