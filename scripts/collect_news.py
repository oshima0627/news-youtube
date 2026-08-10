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
if hasattr(sys.stderr, "reconfigure"):
    # 失敗の原因は stderr に出す。Windows 既定のロケール（cp932）のままだと
    # 日本語の原因メッセージだけが文字化けし、「原因がログにそのまま出る」
    # という各CLIの die()／中止メッセージの目的が損なわれる。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    failures: list[str] = []
    for url in FEEDS:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            items.extend(parse_feed(r.text))
        except Exception as e:            # noqa: BLE001 — フィードごとに握りつぶす
            print(f"! RSSの取得に失敗しました（このフィードは飛ばします）: {url} {e}")
            failures.append(f"{url}: {e}")

    # フィードが1つでも生きていれば従来どおり続行する。
    # 全滅（ネットワーク断・全ホストの障害）と候補0件は、evidence.collect() の
    # EvidenceSourcesUnavailable と同じ「環境不備」であって「今日は題材が
    # 無かった」ではない。空の candidates.json を書いて exit 0 で終わると、
    # run_daily.py 側は候補0件のまま「本日 0/2 本」と表示して終了コード0で
    # 終わり、原因に気づけないまま何日も投稿が止まる。非0終了で知らせる。
    if failures and len(failures) == len(FEEDS):
        print("✗ すべてのRSSフィードの取得に失敗しました。ネットワーク不通など"
              "環境不備の可能性が高いため中止します:\n  "
              + "\n  ".join(failures), file=sys.stderr)
        sys.exit(1)

    picked = rank(items, seen)[:a.limit]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(picked, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    if not picked:
        print(f"✗ 候補が1件もありません（取得した記事 {len(items)} 件、"
              f"失敗したフィード {len(failures)}/{len(FEEDS)}）。"
              "RSSの内容か state/seen.json による除外を確認してください",
              file=sys.stderr)
        sys.exit(1)
    print(f"✓ 候補 {len(picked)} 件 → {OUT.name}")
    for p in picked[:5]:
        print(f"  {p['score']:+3d} {p['title'][:40]}")


if __name__ == "__main__":
    main()
