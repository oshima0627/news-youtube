#!/usr/bin/env python3
"""採用ゲートの歩留まりを測る。**動画は作らない。**

  python scripts/yield_report.py            # work/candidates.json を測る
  python scripts/yield_report.py --refresh  # RSSを取り直してから測る

候補それぞれについて「なぜ落ちたか」を数える。使うのは一次資料の取得元
（国会会議録API）だけで、Anthropic も VOICEVOX も呼ばないので、実行しても
課金は発生しない（実測: 候補20件で約12秒）。

**何のためにあるか。** `state/empty_streak.json` の警告は0本の**日**が3日
続いてから出る（1日3回実行するようになったが、数えるのは実行回数ではなく
日で、確定は日をまたいだ最初の実行で起きるため、実際に気づけるのは早くて
4日目）。収益化要件は90日で3本以上なので、そこまで待ってから気づくのでは
遅いことがある。「今日は何本ぶんの余裕があったか」「足りないなら理由は何か」を
その日のうちに見られるようにしておく。

2026-08-13 の実測では、落ちた理由の内訳が想定と違った。一次資料が取れない
のは20件中4件で、**支配的だったのは同じ出来事の重複除外（11件）**。しかも
その11件は消費税減税6件・熊本地震4件と、たった2つの出来事に集中していた。
各社が同じ出来事を報じるためで、採用ゲートではなく重複除外が効いている。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.evidence import collect  # noqa: E402
from scripts.run_daily import (  # noqa: E402  同じ判定を二重に持たない
    CANDIDATES,
    JST,
    SAME_TOPIC_OVERLAP,
    USED_LOOKBACK_DAYS,
    load_used,
)
from scripts.slots import pending_slots  # noqa: E402

USABLE = "採用可"
NO_EVIDENCE = "根拠なし"
SAME_TOPIC = "既出(出来事)"
SAME_SPEECH = "既出(発言)"


@dataclass(frozen=True)
class Row:
    rank: int
    title: str
    keyword: str
    status: str
    found: int          # 取れた根拠の数
    fresh: int          # うち直近で使っていないもの


def classify(candidates: list[dict], used_urls: set[str],
             used_words: list[set[str]], collect_fn=collect) -> list[Row]:
    """候補ごとに、run_daily と同じ順序で落ちる理由を判定する。

    順序は run_daily.main() に合わせてある（重複除外が先、一次資料の照会は
    その後）。逆にすると、実際には照会されない候補まで数えてしまい、
    「一次資料が取れない率」を実態より高く見せる。
    """
    rows: list[Row] = []
    for i, cand in enumerate(candidates, 1):
        words = set(cand["keyword"].split())
        if any(len(words & used) >= SAME_TOPIC_OVERLAP for used in used_words):
            rows.append(Row(i, cand["title"], cand["keyword"], SAME_TOPIC, 0, 0))
            continue
        try:
            found = collect_fn(cand["keyword"])
        except Exception as e:                      # noqa: BLE001
            # 例外で止めると「測れなかった」ことすら分からない。記録して次へ。
            rows.append(Row(i, cand["title"], cand["keyword"],
                            f"取得失敗: {e}", 0, 0))
            continue
        fresh = [e for e in found if e.source_url not in used_urls]
        status = (USABLE if fresh else
                  (SAME_SPEECH if found else NO_EVIDENCE))
        rows.append(Row(i, cand["title"], cand["keyword"], status,
                        len(found), len(fresh)))
    return rows


def summarize(rows: list[Row], slots: int) -> dict:
    """枠数に対する余裕と、落ちた理由の内訳。"""
    usable = [r for r in rows if r.status == USABLE]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "usable": len(usable),
        "first_usable_rank": usable[0].rank if usable else None,
        "counts": counts,
        "slots": slots,
        "short_of_slots": len(usable) < slots,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true",
                    help="測る前に collect_news.py でRSSを取り直す")
    ap.add_argument("--days-ahead", type=int, default=0, metavar="N",
                    help="何日先の枠数と比べるか（既定は当日の残り枠）")
    a = ap.parse_args()

    if a.refresh:
        subprocess.run([sys.executable, "scripts/collect_news.py",
                        "--limit", "20"], check=True, cwd=ROOT)

    if not CANDIDATES.exists():
        print(f"✗ {CANDIDATES} がありません。--refresh を付けるか、"
              "先に collect_news.py を実行してください", file=sys.stderr)
        sys.exit(1)

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    today = datetime.now(JST).date()
    used_urls, used_words = load_used(today)
    slots = len(pending_slots(datetime.now(JST), a.days_ahead))

    print(f"候補 {len(candidates)} 件 / 直近{USED_LOOKBACK_DAYS}日で使った発言 "
          f"{len(used_urls)} 件 / 対象の枠 {slots}\n")

    rows = classify(candidates, used_urls, used_words)

    print(f"{'順位':>4}  {'状態':12} {'根拠':>4} {'新規':>4}  見出し")
    for r in rows:
        print(f"{r.rank:>4}  {r.status:12} {r.found:>4} {r.fresh:>4}  {r.title[:36]}")

    s = summarize(rows, slots)
    print(f"\n採用可 {s['usable']} 件 / {len(rows)} 件（枠は {slots}）")
    if s["first_usable_rank"]:
        print(f"最上位の採用可は {s['first_usable_rank']} 番目")
    for label, n in sorted(s["counts"].items(), key=lambda kv: -kv[1]):
        if label != USABLE:
            print(f"  {label}: {n} 件")
    if s["short_of_slots"]:
        print("\n! 採用可が枠数に足りません。今日この後に実行しても枠は埋まりません。"
              "RSSの配点（sources.PLUS/MINUS）か重複除外の期間"
              f"（run_daily.USED_LOOKBACK_DAYS={USED_LOOKBACK_DAYS}日）を"
              "見直す判断材料になります")


if __name__ == "__main__":
    main()
