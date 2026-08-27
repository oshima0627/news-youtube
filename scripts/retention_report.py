#!/usr/bin/env python3
"""どこから見られていて、どこまで見られているかを測る。**動画は作らない。**

  python scripts/retention_report.py                 # 直近14日
  python scripts/retention_report.py --days 30
  python scripts/retention_report.py --since 2026-08-12

**何のためにあるか。** 2026-08-27 の実測で、次の2つが同時に分かった。

- チャンネルの再生の **96%がショートのフィード**（`SHORTS`）から来ている。
  検索は3%、関連動画（`RELATED_VIDEO`）は**上位に一度も出てこない**。
- 長尺（`UqjB--sNTKk`）は 8/19〜8/27 で **0再生**。ショート38本の「関連動画」に
  紐づけても回遊は起きなかった。

つまり長尺の不振は題材でもサムネイルでもなく、**乗る面が無い**という話だった。
「題材かサムネイルか」で悩む前に、まず流入元を見る。

同じ実測で、ショートの再生数は **視聴維持率（averageViewPercentage）と一緒に
動いている**ことも見えた（78%を超えた回だけが1,100前後の床を抜けている）。
毎回これを手で調べ直さずに済むよう、CLIにしてある。

`upload_youtube.get_credentials()` を使うので、SCOPES もトークンの失効時の
復旧手順も投稿側と共通。Anthropic も VOICEVOX も呼ばない。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PUBLISHED = ROOT / "state" / "published.json"
DEFAULT_DAYS = 14

# 1回の照会で返す動画の上限。パイプラインは1日2〜3本なので、
# 30日ぶんでも100件あれば足りる。
MAX_VIDEOS = 100


@dataclass(frozen=True)
class Video:
    video_id: str
    views: int
    retention: float
    likes: int


def rank(rows: list[list], mine: set[str]) -> list[Video]:
    """Analytics の行を、パイプライン産だけに絞って再生数の多い順に並べる。

    チャンネルには手作りの古い動画が150本以上ある。混ぜると、
    パイプラインの良し悪しを見ているつもりで別のものを見ることになる。
    """
    videos = [Video(r[0], int(r[1]), float(r[2]), int(r[3]))
              for r in rows if r[0] in mine]
    return sorted(videos, key=lambda v: v.views, reverse=True)


def traffic_share(rows: list[list]) -> list[tuple[str, int, float]]:
    """流入元ごとの再生数と割合。再生が0でも壊れない。"""
    total = sum(int(r[1]) for r in rows)
    out = [(r[0], int(r[1]), (int(r[1]) / total * 100) if total else 0.0)
           for r in rows]
    return sorted(out, key=lambda x: x[1], reverse=True)


def render(videos: list[Video], titles: dict[str, str]) -> list[str]:
    """1行1本。タイトルが引けない動画も行ごと消さずIDで出す
    （消すと「測った本数」が黙って減る）。
    """
    lines = [f"{'再生':>7} {'維持率':>7} {'高評価':>6}  題材"]
    for v in videos:
        lines.append(f"{v.views:7} {v.retention:6.1f}% {v.likes:6}  "
                     f"{titles.get(v.video_id) or v.video_id}")
    return lines


def load_mine() -> set[str]:
    if not PUBLISHED.exists():
        return set()
    videos = json.loads(PUBLISHED.read_text(encoding="utf-8")).get("videos", {})
    return {v["youtube_video_id"] for v in videos.values()
            if v.get("youtube_video_id")}


def fetch_titles(youtube, ids: list[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for at in range(0, len(ids), 50):
        got = youtube.videos().list(
            part="snippet", id=",".join(ids[at:at + 50])).execute()
        for item in got.get("items", []):
            titles[item["id"]] = item["snippet"]["title"]
    return titles


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, metavar="N",
                    help=f"直近N日を見る（既定 {DEFAULT_DAYS}）")
    ap.add_argument("--since", metavar="YYYY-MM-DD", default=None,
                    help="開始日を直接指定する（--days より優先）")
    a = ap.parse_args()

    end = date.today()
    start = (date.fromisoformat(a.since) if a.since
             else end - timedelta(days=a.days))

    from googleapiclient.discovery import build

    from scripts.upload_youtube import get_credentials

    creds = get_credentials()
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    youtube = build("youtube", "v3", credentials=creds)

    def query(**kw):
        return analytics.reports().query(
            ids="channel==MINE", startDate=start.isoformat(),
            endDate=end.isoformat(), **kw).execute().get("rows", [])

    print(f"- 期間: {start} 〜 {end}")

    print("\n■ どこから来ているか")
    for source, views, pct in traffic_share(
            query(metrics="views", dimensions="insightTrafficSourceType")):
        print(f"  {views:7} {pct:5.1f}%  {source}")

    videos = rank(query(metrics="views,averageViewPercentage,likes",
                        dimensions="video", sort="-views",
                        maxResults=MAX_VIDEOS), load_mine())
    if not videos:
        print("\n■ この期間に再生されたパイプライン産の動画はありません")
        return

    print("\n■ どこまで見られているか（パイプライン産のみ）")
    for line in render(videos, fetch_titles(youtube, [v.video_id for v in videos])):
        print("  " + line)


if __name__ == "__main__":
    main()
