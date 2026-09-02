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
import io
import re
from dataclasses import dataclass

import requests
from pypdf import PdfReader

from scripts.evidence import MIN_QUOTE_CHARS, Evidence, has_figure

TIMEOUT = 30
# 公約PDFは実測 7.7MB。取り違えて巨大なファイルを掴まないための上限。
MAX_BYTES = 40 * 1024 * 1024
# テキスト層の無いPDF（画像だけのスキャン）は逐語照合ができない。
# 照合できないものを「一次資料」として通すと、この経路の唯一の関門が
# 無効になるので、短すぎる抽出結果は失敗として扱う。
MIN_PDF_CHARS = 500


class UnknownCandidate(ValueError):
    """許可リストに無い候補を指定した。"""


class QuoteNotFound(ValueError):
    """引用が公約ページに逐語で見つからない。"""


class SourceUnreadable(RuntimeError):
    """一次資料からテキストを取り出せない（PDFにテキスト層が無い等）。"""


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
    # 各候補が公開している政策集（PDF）。要約ページより踏み込んだ記述が要る
    # ときに使う。**両候補ぶんを対で入れてある**——片方の候補についてだけ
    # 詳しい資料が使える状態にすると、深掘りが常に一方に偏る。
    "koja-detail": ManifestoSource(
        url="https://kojagenta.com/wp-content/themes/kojagenta_2607/assets/"
            "img/manifest/%E6%B2%96%E7%B8%84%E3%82%92%E5%89%8D%E3%81%AB%E9%80"
            "%B2%E3%82%81%E3%82%8B120%E3%81%AE%E6%94%BF%E7%AD%96.pdf",
        person="古謝玄太",
        context="古謝玄太「沖縄を前に進める120の政策」",
    ),
    "tamaki-detail": ManifestoSource(
        url="https://tamakidenny.com/wp2/wp-content/uploads/2026/08/"
            "2026%E7%8E%89%E5%9F%8E%E3%83%87%E3%83%8B%E3%83%BC%E7%9F%A5%E4%BA"
            "%8B%E9%81%B8%E6%94%BF%E7%AD%96%E9%9B%86.pdf",
        person="玉城デニー",
        context="玉城デニー 知事選政策集",
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


def _pdf_text(blob: bytes) -> str:
    """PDF のテキスト層を取り出す。

    画像だけのPDFでは空に近い文字列が返る。それを黙って通すと、
    逐語照合が「何とも一致しない」ではなく「照合対象が無い」状態になり、
    関門として働かなくなる。短すぎたら失敗として送出する。
    """
    pages = PdfReader(io.BytesIO(blob)).pages
    text = "\n".join((p.extract_text() or "") for p in pages)
    if len(text.strip()) < MIN_PDF_CHARS:
        raise SourceUnreadable(
            f"PDFからテキストを取り出せませんでした（{len(text.strip())}字）。"
            "画像だけのPDFは逐語照合ができないので一次資料に使えません")
    return text


def _fetch(url: str) -> str:
    """公約ページ／政策集の本文テキストを取る。テストはここを差し替える。"""
    r = requests.get(url, timeout=TIMEOUT,
                     headers={"User-Agent": "news-youtube/1.0"})
    r.raise_for_status()
    blob = r.content
    if len(blob) > MAX_BYTES:
        raise SourceUnreadable(
            f"一次資料が大きすぎます: {len(blob)} > {MAX_BYTES}（{url}）")
    ctype = r.headers.get("content-type", "").lower()
    if "application/pdf" in ctype or url.lower().endswith(".pdf"):
        return _pdf_text(blob)
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
