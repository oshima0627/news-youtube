#!/usr/bin/env python3
"""描画の共通部品。tora-kirinuki/scripts/draw.py から移植した。

配色はニュース向けに、濃紺地に白、差し色に赤。
"""

from __future__ import annotations

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


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
         max_w: int) -> list[str]:
    """日本語は単語境界が無いので、幅を見て1文字ずつ折り返す。"""
    text = normalize_newlines(text)
    lines, cur = [], ""
    for ch in text:
        b = draw.textbbox((0, 0), cur + ch, font=font)
        if b[2] - b[0] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


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
