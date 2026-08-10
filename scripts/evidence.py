#!/usr/bin/env python3
"""一次資料の取得と採用ゲート。

このモジュールがパイプライン全体の関門になる。
**根拠が取れなければ動画を作らない**を採用条件そのものにすることで、
YouTube の量産型コンテンツ判定と、完全自動での事実誤認の両方を
同じ1箇所で塞いでいる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# 一次資料として認めるホストのサフィックス。ここを広げると「解説」が「転載」に変わる
# 許可範囲: 日本政府機関（*.go.jp）のオフィシャルサイト
EVIDENCE_HOST_SUFFIX = ".go.jp"

MIN_QUOTE_CHARS = 12
_FIGURE_RE = re.compile(r"[0-9０-９]")


@dataclass(frozen=True)
class Evidence:
    kind: str          # "speech" | "statistics" | "release"
    source_url: str    # 一次資料のURL
    figure: str        # 具体的な数値（無ければ空）
    quote: str         # 逐語引用（無ければ空）
    context: str       # 会議名・統計名・発表日など


def _is_primary_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(EVIDENCE_HOST_SUFFIX)


def is_admissible(ev: Evidence) -> bool:
    """出典URLと、具体的な数値または逐語引用の両方が揃っていれば True。"""
    if not ev.source_url or not _is_primary_host(ev.source_url):
        return False
    has_quote = len(ev.quote.strip()) >= MIN_QUOTE_CHARS
    has_figure = bool(_FIGURE_RE.search(ev.figure))
    return has_quote or has_figure


import requests

KOKKAI_ENDPOINT = "https://kokkai.ndl.go.jp/api/speech"
TIMEOUT = 20


def parse_speeches(payload: dict) -> list[Evidence]:
    """国会会議録APIの応答を Evidence に変換する。

    「次に。」のような進行発言が大量に混ざるので、
    根拠になる長さの無いものはここで落とす。
    """
    out: list[Evidence] = []
    for rec in payload.get("speechRecord") or []:
        quote = (rec.get("speech") or "").strip()
        if len(quote) < MIN_QUOTE_CHARS:
            continue
        speaker = rec.get("speaker") or ""
        context = (f"第{rec.get('session')}回国会 {rec.get('nameOfHouse')}"
                   f"{rec.get('nameOfMeeting')} {rec.get('date')} {speaker}")
        out.append(Evidence(kind="speech",
                            source_url=rec.get("speechURL") or "",
                            figure="",
                            quote=quote,
                            context=context.strip()))
    return out


def search_speeches(keyword: str, limit: int = 10) -> list[Evidence]:
    """国会会議録を全文検索する。認証キーは不要。"""
    r = requests.get(KOKKAI_ENDPOINT, timeout=TIMEOUT, params={
        "any": keyword,
        "recordPacking": "json",
        "maximumRecords": min(limit, 100),
    })
    r.raise_for_status()
    return parse_speeches(r.json())
