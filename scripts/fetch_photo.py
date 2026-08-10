#!/usr/bin/env python3
"""画像を1枚落として work/<id>/ に置く。

  python scripts/fetch_photo.py work/<id> <画像URL>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.photos import download  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    ap.add_argument("url")
    a = ap.parse_args()

    rec = download(a.url, a.workdir / "photo.jpg")
    (a.workdir / "license.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ {rec['file']}\n{rec['attribution']}")


if __name__ == "__main__":
    main()
