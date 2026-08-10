#!/usr/bin/env python3
"""題材の発見。

**RSSは「何が起きたか」を知るためだけに使い、記事の文章は台本に渡さない。**
内容は後段で一次資料から書き起こすので、記事の翻案にならない。

配点は既存48本の実績に合わせた。伸びたのは対中外交・政治家の発言・
国内政策で、日本の当事者性が薄い題材（米中貿易など）は実測で下位に沈んだ。
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET

FEEDS = (
    "https://www3.nhk.or.jp/rss/news/cat0.xml",   # 主要
    "https://www3.nhk.or.jp/rss/news/cat4.xml",   # 政治
    "https://news.yahoo.co.jp/rss/topics/domestic.xml",
)

PLUS = {
    "中国": 4, "台湾": 3, "外交": 3, "防衛": 3, "自衛隊": 3, "国連": 2,
    "総理": 3, "大臣": 2, "国会": 2, "議員": 2, "答弁": 3, "発言": 2,
    "炎上": 3, "批判": 2, "撤回": 2, "謝罪": 2, "矛盾": 3,
    "外国人": 3, "税": 2, "物価": 2, "年金": 2, "移民": 3,
}
MINUS = {"米中": 4, "欧州": 2, "アフリカ": 3, "中南米": 3, "スポーツ": 4, "芸能": 3}
JAPAN = ("日本", "国内", "政府", "総理", "自衛隊", "国会", "円")


def score(title: str) -> int:
    s = sum(w for k, w in PLUS.items() if k in title)
    s -= sum(w for k, w in MINUS.items() if k in title)
    if not any(k in title for k in JAPAN):
        s -= 2                      # 日本が出てこない題材は伸びない
    return s


def make_id(title: str) -> str:
    return hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]


def _keyword(title: str) -> str:
    """一次資料を引くための検索語。記号と定型の飾りを落とす。"""
    t = re.sub(r"[【】\[\]（）()「」『』｜|…、。！？!?]", " ", title)
    return " ".join(t.split())[:40]


def parse_feed(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    out: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title and link:
            out.append({"title": title, "link": link})
    return out


def rank(items: list[dict], seen: set[str]) -> list[dict]:
    """既出を除き、得点の高い順に並べる。"""
    out: list[dict] = []
    for it in items:
        nid = make_id(it["title"])
        if nid in seen:
            continue
        seen.add(nid)               # 同一実行内の重複も落とす
        out.append({
            "id": nid,
            "title": it["title"],
            "link": it["link"],
            "keyword": _keyword(it["title"]),
            "category": "政治",
            "score": score(it["title"]),
        })
    return sorted(out, key=lambda x: x["score"], reverse=True)
