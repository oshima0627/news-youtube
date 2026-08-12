#!/usr/bin/env python3
"""描画の共通部品。tora-kirinuki/scripts/draw.py から移植した。

配色はニュース向けに、濃紺地に白、差し色に赤。
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import ImageDraw, ImageFont

FONT_SANS = [
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]

NAVY = (16, 24, 43)
RED = (232, 48, 52)
INK = (250, 250, 252)
MUTED = (150, 158, 176)
# テロップの文字色。濃紺地の上で最も視認性が高くなる暖色を選んでいる。
# 白のままだと引用カードの文字と区別がつかず、どちらが「いま読んでいる所」か
# 分からない。
ORANGE = (255, 150, 26)


# FONT_SANS が全滅したことを一度だけ警告するためのフラグ。pick_font は
# 1フレームあたり何十回も呼ばれるので、毎回出すと他の警告が埋もれる。
_warned_no_font = False


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    global _warned_no_font
    for p in FONT_SANS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    # load_default() は日本語グリフを持たないため、このまま進むと文字が
    # すべて豆腐（□）になった動画がそのまま公開される。完全自動なので
    # 誰も気づかないまま公開されうる。必ず警告を出す。
    if not _warned_no_font:
        _warned_no_font = True
        print("! 日本語フォントが1つも見つかりません（PIL の load_default に"
              "フォールバックします）。このままだと文字が豆腐（□）になった"
              f"動画が公開されます。探した場所: {', '.join(FONT_SANS)}")
    return ImageFont.load_default()


_KANJI_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_SMALL_UNIT = {"十": 10, "百": 100, "千": 1000}     # 数の中の位取り
_LARGE_UNIT = ("兆", "億", "万")                    # 表記として残す大きい単位
_LARGE_LEAD = "万億兆"
_NUM_CHARS = "".join(_KANJI_DIGIT) + "十百千" + _LARGE_LEAD

# 数字1文字だけのときに「本当に数量か」を決める手がかり。ここに無い語が続く
# ときは変換しない。「一部」「一方」「九州」「第三者」「十分」を数値と
# 見なして壊さないための関門で、**曖昧な助数詞（分・時・度・部・者など）は
# 意図的に入れていない**。「一分」が「1分」にならない代わりに、
# 「十分（じゅうぶん）」が「10分」になる事故を防いでいる。
_SAFE_UNITS = (
    "パーセント", "ポイント", "メートル", "キロ", "グラム", "リットル", "トン",
    "か月", "カ月", "箇月", "か国", "カ国", "箇国", "か所", "カ所", "箇所",
    "時間", "分間", "世帯", "議席", "ウォン", "ユーロ", "ドル",
    "％", "%", "円", "人", "件", "名", "票", "席", "個", "本", "台", "隻",
    "機", "社", "校", "回", "歳", "年", "月", "日", "週", "割", "倍",
    "秒", "元",
)

_RUN_RE = re.compile(rf"[{_NUM_CHARS}]+(?:・[{_NUM_CHARS}]+)?")
_DECIMAL_RE = re.compile(
    rf"^([{''.join(_KANJI_DIGIT)}]+)・([{''.join(_KANJI_DIGIT)}]+)([{_LARGE_LEAD}]?)$")


def _parse_group(text: str) -> int:
    """十・百・千までの位取りを解いて整数にする。

    「三千七十七」→ 3077、「四百十三」→ 413、「一〇」→ 10。
    位を表す漢字の前に数字が無いときは1とみなす（「十三」→ 13）。
    """
    total = cur = 0
    has_digit = False
    for ch in text:
        if ch in _KANJI_DIGIT:
            cur = cur * 10 + _KANJI_DIGIT[ch]
            has_digit = True
        elif ch in _SMALL_UNIT:
            total += (cur if has_digit and cur else 1) * _SMALL_UNIT[ch]
            cur = 0
            has_digit = False
    return total + cur


def _format_numeral(run: str) -> str:
    """漢数字の並びを算用数字に組み直す。**万・億・兆は単位として残す。**

    「千六百三十億」→「1630億」、「三十四兆三千七十七億」→「34兆3077億」。
    全部の桁を数字にすると（163000000000）読めなくなるので、
    新聞やテレビと同じく大きい単位は漢字のまま残す。
    """
    decimal = _DECIMAL_RE.match(run)
    if decimal:
        whole, frac, unit = decimal.groups()
        digits = "".join(str(_KANJI_DIGIT[c]) for c in frac)
        return f"{_parse_group(whole)}.{digits}{unit}"

    rest, parts = run, []
    for unit in _LARGE_UNIT:
        head, sep, tail = rest.partition(unit)
        if not sep:
            continue
        value = _parse_group(head)
        if value:
            parts.append(f"{value}{unit}")
        rest = tail
    if rest or not parts:
        value = _parse_group(rest)
        if value or not parts:
            parts.append(str(value))
    return "".join(parts)


def _should_convert(run: str, following: str) -> bool:
    """その並びを数値として書き換えてよいか。

    判断できないものは変換しない。表記が読みづらいのは我慢できるが、
    「一部」を「1部」に、「九州」を「9州」に変えるのは意味が壊れる。
    """
    if run[0] in _LARGE_LEAD:
        # 「万一」「億劫」のように大きい単位で始まるものは数ではない
        return False
    if len(run) >= 2:
        # 「一〇」「四十五」「三千七十七億」。2文字以上並ぶ漢数字は
        # ほぼ確実に数量で、単語の一部（一部・九州・第三者）は1文字で終わる
        return True
    return following.startswith(_SAFE_UNITS)


def normalize_numerals(text: str) -> str:
    """漢数字を算用数字に直す。**表記だけを変え、値は変えない。**

    国会会議録は数字を漢字で書き起こすので、そのまま画面に出すと
    「一〇％」「千六百三十億円」のように読みづらい。テレビや新聞と同じ表記
    （「10%」「1630億円」）にする。

    引用が一次資料の逐語であることの検証（run_daily.ensure_grounded_card）は
    **変換前の文字列**に対して行う。ここは画面に出す直前の表記だけを扱う。
    """
    def replace(m: re.Match) -> str:
        run = m.group()
        if not _should_convert(run, text[m.end():]):
            return run
        return _format_numeral(run)

    return _RUN_RE.sub(replace, text).replace("％", "%")


def normalize_newlines(text: str) -> str:
    """改行を空白に正規化する。

    `textbbox` は `\n` を含む文字列を複数行として測定するため、そのまま
    `fit_font()` / `wrap()` に渡すと「1つの論理行」として幅を測る想定と
    ズレ、行間計算が崩れて帯からのはみ出しや行の重なりを招く。ナレーション
    はClaudeが生成するため改行が混ざりうるので、両関数の入口で必ず正規化する。
    """
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: int,
             start: int) -> ImageFont.FreeTypeFont:
    """幅に収まる最大サイズのフォントを返す。"""
    text = normalize_newlines(text)
    size = start
    while size > 14:
        f = pick_font(size)
        b = draw.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= max_w:
            return f
        size -= 2
    return pick_font(14)


# 行頭に置いてはいけない文字（禁則処理）。句読点や閉じ括弧が次の行の先頭に
# 落ちると、テロップでは「。」だけの行ができて目立つ（実測で発生した）。
_NO_LINE_START = "、。，．！？」』）］｝〉》”’ー・"


# 英数字の連なりは途中で折り返さない。1文字ずつ送ると「G7」が
# 「G」／「7」に割れ、「10%」が「1」／「0%」に割れる（実際に起きた）。
_ATOM_RE = re.compile(r"[0-9A-Za-z]+[%％]?|.", re.S)


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
         max_w: int) -> list[str]:
    """日本語は単語境界が無いので、幅を見て折り返す。

    英数字の連なりは1かたまりとして扱い、途中では切らない。
    行頭に来てはいけない文字は前の行に残す（禁則処理）。幅を少し
    超えることになるが、「。」だけの行を作るよりは収まりがよい。
    """
    text = normalize_newlines(text)
    lines, cur = [], ""
    for atom in _ATOM_RE.findall(text):
        b = draw.textbbox((0, 0), cur + atom, font=font)
        if b[2] - b[0] > max_w and cur and atom not in _NO_LINE_START:
            lines.append(cur)
            cur = atom
        else:
            cur += atom
    if cur:
        lines.append(cur)
    return lines


def fit_wrapped(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int,
                max_lines: int, start: int = 150, minimum: int = 40,
                leading: float = 1.22):
    """折り返した上で幅と高さに収まる、いちばん大きいフォントを返す。

    `fit_font()` は1行に収める前提なので、短い見出しでも指定の上限までしか
    大きくならず、帯に余白が残る。見出しは画面で一番強い要素にしたいので、
    **2行に折り返してでも限界まで大きくする**。

    戻り値は (font, lines)。minimum まで縮めても収まらなければ、その大きさで
    折り返した結果をそのまま返す（切り捨ての判断は呼び出し側に任せる）。
    """
    size = start
    while size > minimum:
        font = pick_font(size)
        lines = wrap(draw, text, font, max_w)
        if len(lines) <= max_lines and int(size * leading) * len(lines) <= max_h:
            return font, lines
        size -= 4
    font = pick_font(minimum)
    return font, wrap(draw, text, font, max_w)


def truncate_ellipsis(draw: ImageDraw.ImageDraw, text: str,
                       font: ImageFont.FreeTypeFont, max_w: int) -> tuple[str, bool]:
    """幅に収まるよう末尾を省略記号(…)で切り詰める。

    `fit_font()` はフォントサイズを14までしか縮めないため、最小サイズでも
    収まらない極端に長い文字列（一次資料の出典表記など）は、これで折り返し
    せず1行のまま切り詰める。戻り値は (表示用文字列, 切り詰めたか) 。
    """
    b = draw.textbbox((0, 0), text, font=font)
    if b[2] - b[0] <= max_w:
        return text, False

    cur = text
    while cur:
        cand = cur + "…"
        b = draw.textbbox((0, 0), cand, font=font)
        if b[2] - b[0] <= max_w:
            return cand, True
        cur = cur[:-1]
    return "…", True
