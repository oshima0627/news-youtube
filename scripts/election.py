#!/usr/bin/env python3
"""選挙期間中だけ使う、候補者の公約ページを一次資料とする採用ゲート。

**run_daily.py の関門（evidence.collect / EVIDENCE_HOST_SUFFIX = ".go.jp"）は
一切触らない。** ここは独立した2つ目の扉で、そのぶん通れるものを極端に狭く
してある。選挙が終わったらこのファイルと scripts/run_election.py を消せば、
日次パイプラインは元の1経路に戻る。

なぜホスト単位で許可しないか
----------------------------
`EVIDENCE_HOST_SUFFIX` を広げる（案A）と、その変更は**今後の全動画**に効く。
"kojagenta.com" をホストとして許可しても、そのドメインの任意のページが
通るようになる。ここでは URL を丸ごと固定し、**通れる一次資料が2つしか
存在しない**状態にしてある。

引用の検証
----------
国会会議録の系統（evidence.find_passage）が見ているのは「検索語が同じ文脈に
2語以上固まって現れるか」だけで、引用が見出しを裏付けているかは判定して
いない（CLAUDE.md「未解決」の節）。こちらは**引用そのものがページに逐語で
存在するか**を機械的に確かめるので、その1点についてはむしろ厳しい。

対称性について
--------------
許可リストに両候補を入れてあるので、どちらか一方の資料しか使えない、という
状態にはならない。ただし**本数の対称性はコードでは強制していない**。
何本ずつ作るかは編集判断であり、ここで縛ると「片方の候補について続報が
出せない」という別の歪みになる。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import requests

from scripts.evidence import MIN_QUOTE_CHARS, Evidence, has_figure

TIMEOUT = 20


class UnknownCandidate(ValueError):
    """許可リストに無い候補を指定した。"""


class QuoteNotFound(ValueError):
    """引用が公約ページに逐語で見つからない。"""


@dataclass(frozen=True)
class ManifestoSource:
    url: str      # 一次資料そのもの。ここに書いた1本だけが通る
    person: str   # ja.wikipedia の記事名。commons.resolve がこの名前で画像を引く
    context: str  # 画面に出す出典キャプション


# 2026年沖縄県知事選（告示 2026-08-27 / 投開票 2026-09-13）の主要2候補。
# **両方入っていること**を tests/test_election.py が縛っている。
MANIFESTO_SOURCES: dict[str, ManifestoSource] = {
    "koja": ManifestoSource(
        url="https://kojagenta.com/manifest/",
        person="古謝玄太",
        context="古謝玄太 公約（げんきな沖縄を創る県民の会）",
    ),
    "tamaki": ManifestoSource(
        url="https://tamakidenny.com/policy2026/",
        person="玉城デニー",
        context="玉城デニー 2026年政策",
    ),
}

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>",
                     re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _strip_html(raw: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", raw))


def _squeeze(text: str) -> str:
    """空白（半角・全角・改行）を全部落とす。

    照合の前処理。ページ側の改行や全角空白の入り方だけで関門が落ちるのは
    無意味だが、**文字そのものが違うものは通さない**（落とすのは空白だけ）。
    """
    return _WS_RE.sub("", text.replace("\u3000", " "))


def _fetch(url: str) -> str:
    """公約ページの本文テキストを取る。テストはここを差し替える。"""
    r = requests.get(url, timeout=TIMEOUT,
                     headers={"User-Agent": "news-youtube/1.0"})
    r.raise_for_status()
    return _strip_html(r.text)


def collect(candidate: str, quote: str, *, figure: str = "") -> Evidence:
    """候補者の公約ページを一次資料として Evidence を返す。

    `quote` はページに**逐語で存在すること**を確かめてから採用する。
    見つからなければ QuoteNotFound を送出し、呼び出し側は動画を作らない。
    """
    src = MANIFESTO_SOURCES.get(candidate)
    if src is None:
        raise UnknownCandidate(
            f"許可リストに無い候補です: {candidate!r}。"
            f"使えるのは {sorted(MANIFESTO_SOURCES)} だけです")

    quote = quote.strip()
    if len(quote) < MIN_QUOTE_CHARS:
        raise QuoteNotFound(
            f"引用が短すぎます（{len(quote)}字 < {MIN_QUOTE_CHARS}字）: {quote!r}。"
            "数字だけを切り出すと何の数字か分からなくなります")

    if figure and not has_figure(figure):
        # 採用ゲートと数値カードの出し分けで同じ基準を使う
        # （evidence.has_figure。CLAUDE.md「判定基準を2箇所に書かない」）。
        raise ValueError(
            f"figure が数量ではありません: {figure!r}。"
            "数値カードにはモデルや書き手が作った値ではなく"
            "一次資料の数量だけを出します")

    page = _squeeze(_fetch(src.url))
    if _squeeze(quote) not in page:
        raise QuoteNotFound(
            f"引用が公約ページに逐語で見つかりません: {quote[:40]!r}\n"
            f"  ページ: {src.url}\n"
            "  一字一句そのままの部分文字列にしてください")

    return Evidence(kind="manifesto", source_url=src.url, figure=figure,
                    quote=quote, context=src.context, speaker=src.person)
