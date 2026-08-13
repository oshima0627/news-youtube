#!/usr/bin/env python3
"""チャンネルへの投稿が途切れていないかを外から見る。**動画は作らない。**

  python scripts/watch_channel.py              # 直近7日に1本も無ければ終了コード1
  python scripts/watch_channel.py --within 14

見るのはログではなく **YouTube 側の実際の公開状況**。ログを監視すると
「スクリプトは正常終了したがアップロードは失敗していた」「PCごと落ちた」を
取りこぼす。外から「動画が増えているか」だけを見れば、原因が何であれ
**止まっていること**そのものを捕まえられる。

**標準ライブラリだけで書く。** GitHub Actions から `pip install` 無しで
走らせるため。同じ理由で他の `scripts/*` を import しない（`run_daily` を
import すると PIL・pydantic・janome まで引きずられる）。
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# run_daily.py にも同じ定数があるが、**あえて重複させている**。
# import すると上記のとおり重い依存を引きずり、Actions 環境で落ちるため。
CHANNEL_ID = "UCYHTfHJOoETzvpx-VZlUTng"

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
DEFAULT_WITHIN_DAYS = 7
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class Entry:
    published: datetime
    title: str


def parse_entries(xml: str) -> list[Entry]:
    """feed から公開日時とタイトルを取り出す。

    公開日時が無い entry は飛ばす。日時が読めないものを 0 や「今」として
    扱うと、止まっているのに動いているように見えるか、その逆になる。
    """
    root = ET.fromstring(xml)
    out: list[Entry] = []
    for entry in root.findall("a:entry", ATOM):
        published = entry.findtext("a:published", namespaces=ATOM)
        if not published:
            continue
        out.append(Entry(published=datetime.fromisoformat(published),
                         title=(entry.findtext("a:title", namespaces=ATOM) or "").strip()))
    return out


def count_recent(entries: list[Entry], now: datetime, within_days: int) -> int:
    """直近 within_days 日に公開された本数。境界は含める。"""
    limit = now - timedelta(days=within_days)
    return sum(1 for e in entries if e.published >= limit)


def latest(entries: list[Entry]) -> Entry | None:
    """いちばん新しい公開。1本も無ければ None。"""
    return max(entries, key=lambda e: e.published, default=None)
