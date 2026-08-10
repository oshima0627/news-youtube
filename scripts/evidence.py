#!/usr/bin/env python3
"""一次資料の取得と採用ゲート。

このモジュールがパイプライン全体の関門になる。
**根拠が取れなければ動画を作らない**を採用条件そのものにすることで、
YouTube の量産型コンテンツ判定と、完全自動での事実誤認の両方を
同じ1箇所で塞いでいる。
"""

from __future__ import annotations

import os
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
    records = payload.get("speechRecord") or []
    if isinstance(records, dict):
        # 繰り返し要素が1件のとき、配列ではなくオブジェクト単体で返ってくる実装があるためのガード
        records = [records]
    for rec in records:
        quote = (rec.get("speech") or "").strip()
        if len(quote) < MIN_QUOTE_CHARS:
            continue
        session = rec.get("session")
        house = rec.get("nameOfHouse") or ""
        meeting = rec.get("nameOfMeeting") or ""
        date = rec.get("date") or ""
        speaker = rec.get("speaker") or ""
        parts = [
            f"第{session}回国会" if session else "",
            f"{house}{meeting}",
            date,
            speaker,
        ]
        context = " ".join(p for p in parts if p)
        out.append(Evidence(kind="speech",
                            source_url=rec.get("speechURL") or "",
                            figure="",
                            quote=quote,
                            context=context))
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


ESTAT_ENDPOINT = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList"


def search_statistics(keyword: str) -> list[Evidence]:
    """e-Stat の統計表を検索する。appId が無ければ何も返さない。

    統計表そのものは数値の塊なので、ここでは「どの統計に当たれば数字が
    あるか」までを Evidence にし、figure には統計表の件数を入れる。
    """
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        return []
    r = requests.get(ESTAT_ENDPOINT, timeout=TIMEOUT, params={
        "appId": app_id, "searchWord": keyword, "limit": 5,
    })
    r.raise_for_status()
    body = r.json().get("GET_STATS_LIST", {})
    if str(body.get("RESULT", {}).get("STATUS")) != "0":
        return []
    tables = body.get("DATALIST_INF", {}).get("TABLE_INF") or []
    if isinstance(tables, dict):
        tables = [tables]

    out: list[Evidence] = []
    for t in tables:
        stats_id = t.get("@id") or ""
        title = t.get("STATISTICS_NAME") or ""
        survey = t.get("SURVEY_DATE") or ""
        if not stats_id:
            continue
        out.append(Evidence(
            kind="statistics",
            source_url=f"https://www.e-stat.go.jp/dbview?sid={stats_id}",
            figure=f"{survey}" if survey else stats_id,
            quote="",
            context=f"e-Stat {title}".strip()))
    return out


def collect(keyword: str) -> list[Evidence]:
    """3系統に当てて、採用条件を満たした根拠だけを返す。

    落ちている系統はスキップし、残りで判定を続ける。
    全系統が失敗したら空を返す（＝その題材は作らない）。
    """
    found: list[Evidence] = []
    for fetch in (lambda: search_speeches(keyword),
                  lambda: search_statistics(keyword)):
        try:
            found.extend(fetch())
        except Exception as e:            # noqa: BLE001 — 系統ごとに握りつぶす
            print(f"! 一次資料の取得に失敗しました（この系統は飛ばします）: {e}")
    return [ev for ev in found if is_admissible(ev)]
