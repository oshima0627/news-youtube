#!/usr/bin/env python3
"""RSSを巡回して候補を作る。

  python scripts/collect_news.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする
SEEN = ROOT / "state" / "seen.json"
OUT = ROOT / "work" / "candidates.json"

from scripts.sources import FEEDS, parse_feed, rank  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))
               if SEEN.exists() else [])

    items: list[dict] = []
    for url in FEEDS:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            items.extend(parse_feed(r.text))
        except Exception as e:            # noqa: BLE001
            print(f"! RSSの取得に失敗しました（このフィードは飛ばします）: {url} {e}")

    picked = rank(items, seen)[:a.limit]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(picked, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"✓ 候補 {len(picked)} 件 → {OUT.name}")
    for p in picked[:5]:
        print(f"  {p['score']:+3d} {p['title'][:40]}")


if __name__ == "__main__":
    main()
