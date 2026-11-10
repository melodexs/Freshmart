"""Remove Python/test caches. Run with `make clean`."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}

for path in ROOT.rglob("*"):
    if path.is_dir() and path.name in NAMES and ".venv" not in path.parts:
        shutil.rmtree(path, ignore_errors=True)
        print("removed", path.relative_to(ROOT))
