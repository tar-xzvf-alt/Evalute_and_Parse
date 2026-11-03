"""Headless entrypoint: python -m parsevk (also usable by absolute file path)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from collection_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
