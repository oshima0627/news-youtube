#!/usr/bin/env python3
"""縦型ショートの描画。

  上部の帯   見出し（2行まで）
  中央の穴   上に実写、下に根拠カード（数値カード or 引用カード）
  下部の帯   要点を字幕で（4行まで）

根拠カードが「解説」の実体になる。これが無いと画像スライドショーと
見分けがつかず、量産型コンテンツの判定に近づく。

カードには必ず一次資料の出典キャプションが入る。したがって
**カードに出す文字列は一次資料に由来していなければならない。**
一次資料が「発言」のとき（＝ Evidence.figure が空のとき）は、値をモデルに
作らせる数値カード（render_figure）ではなく、逐語引用をそのまま出す
引用カード（render_quote）を使う。捏造された値に一次資料の出典が付く、
という設計方針の破れを画面側でも塞ぐため。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from scripts.draw import (INK, MUTED, NAVY, RED, fit_font, pick_font,
                           truncate_ellipsis, wrap)

SHORT_SIZE = (1080, 1920)
HOLE_TOP = 460            # 上帯の高さ
HOLE_BOTTOM = 1460        # 下帯の始まり
PHOTO_H = 659             # 穴のうち実写が占める高さ
FIGURE_H = HOLE_BOTTOM - (HOLE_TOP + PHOTO_H)


def render_frame(headline: str, subtitle: str) -> Image.Image:
    """上下の帯を描き、中央を透過にして返す。"""
    w, h = SHORT_SIZE
    img = Image.new("RGBA", SHORT_SIZE, NAVY + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, HOLE_TOP, w, HOLE_BOTTOM], fill=(0, 0, 0, 0))

    m = int(w * 0.06)
    avail = w - m * 2

    f = fit_font(d, headline[:20], avail, 92)
    y = 96
    headline_lines = wrap(d, headline, f, avail)
    if len(headline_lines) > 2:
        print(f"! 見出しが{len(headline_lines) - 2}行溢れて切り捨てられました: {headline[:20]}")
    for ln in headline_lines[:2]:
        d.text((m, y), ln, font=f, fill=INK + (255,),
               stroke_width=8, stroke_fill=(0, 0, 0, 255))
        d.text((m, y), ln, font=f, fill=INK + (255,))
        y += int(f.size * 1.26)

    d.rectangle([m, HOLE_BOTTOM + 40, m + 120, HOLE_BOTTOM + 48],
                fill=RED + (255,))

    fs = pick_font(58)
    y = HOLE_BOTTOM + 84
    subtitle_lines = wrap(d, subtitle, fs, avail)
    if len(subtitle_lines) > 4:
        print(f"! 字幕が{len(subtitle_lines) - 4}行溢れて切り捨てられました: {subtitle[:20]}")
    for ln in subtitle_lines[:4]:
        d.text((m, y), ln, font=fs, fill=INK + (255,))
        y += 76
    return img


SOURCE_MAX_LINES = 2
QUOTE_MAX_LINES = 2


def _draw_source(d: ImageDraw.ImageDraw, source: str, m: int, avail: int) -> None:
    """カード下端の出典キャプション。数値カード・引用カードで共通。"""
    sf = pick_font(34)
    source_lines = wrap(d, f"出典: {source}", sf, avail)
    if len(source_lines) > SOURCE_MAX_LINES:
        print(f"! 出典が{len(source_lines) - SOURCE_MAX_LINES}行溢れて切り捨てられました: {source[:20]}")
    shown = source_lines[:SOURCE_MAX_LINES]
    y = FIGURE_H - 56 - (len(shown) - 1) * 40
    for ln in shown:
        d.text((m, y), ln, font=sf, fill=MUTED)
        y += 40


def render_figure(label: str, value: str, source: str) -> Image.Image:
    """数値カード。穴の下側にぴったり収まる大きさで返す。

    **一次資料が実際の数値（Evidence.figure）を持っている系統でのみ使うこと。**
    value は台本生成モデルの出力なので、figure が空の系統（発言）で使うと
    モデルが作った数値に一次資料の出典キャプションが付く。その場合は
    `render_quote()` を使う。

    label / value / source はいずれもカード幅からはみ出す可能性がある
    （source は一次資料の context＝会議名＋日付＋発言者が入るため特に長くなる）。
    `fit_font()` は最小14ptまでしか縮めないので、それでも収まらない場合は
    省略記号（label / value）または複数行への折り返し（source）で収め、
    切り詰めが発生したら警告を出す。
    """
    w = SHORT_SIZE[0]
    img = Image.new("RGB", (w, FIGURE_H), NAVY)
    d = ImageDraw.Draw(img)
    m = int(w * 0.06)
    avail = w - m * 2

    d.rectangle([0, 0, w, 6], fill=RED)

    lf = pick_font(44)
    label_text, label_cut = truncate_ellipsis(d, label, lf, avail)
    if label_cut:
        print(f"! ラベルが幅に収まらず切り詰められました: {label[:20]}")
    d.text((m, 28), label_text, font=lf, fill=MUTED)

    f = fit_font(d, value, avail, 150)
    value_text, value_cut = truncate_ellipsis(d, value, f, avail)
    if value_cut:
        print(f"! 数値が幅に収まらず切り詰められました: {value[:20]}")
    d.text((m, 92), value_text, font=f, fill=INK)

    _draw_source(d, source, m, avail)
    return img


def render_quote(text: str, source: str) -> Image.Image:
    """引用カード。数値カードと同じ大きさ・同じ出典キャプションの流儀で返す。

    一次資料が「発言」のときに使う。画面に出すのは逐語引用そのもの（かぎ括弧で
    囲む）なので、出典キャプションが指す一次資料と画面の文字列が必ず一致する。
    数値カードのように「モデルが作った値に一次資料の出典が付く」余地が無い。

    text は1行に収まらないことを前提に、2行に収まる最大のフォントサイズを
    探して折り返す（`fit_font()` は1行前提なので使えない）。
    """
    w = SHORT_SIZE[0]
    img = Image.new("RGB", (w, FIGURE_H), NAVY)
    d = ImageDraw.Draw(img)
    m = int(w * 0.06)
    avail = w - m * 2

    d.rectangle([0, 0, w, 6], fill=RED)

    d.text((m, 24), "一次資料より", font=pick_font(36), fill=MUTED)

    body = f"「{text}」"
    size = 60
    f = pick_font(size)
    lines = wrap(d, body, f, avail)
    while len(lines) > QUOTE_MAX_LINES and size > 34:
        size -= 4
        f = pick_font(size)
        lines = wrap(d, body, f, avail)
    if len(lines) > QUOTE_MAX_LINES:
        print(f"! 引用が{len(lines) - QUOTE_MAX_LINES}行溢れて切り捨てられました: {text[:20]}")

    y = 76
    for ln in lines[:QUOTE_MAX_LINES]:
        d.text((m, y), ln, font=f, fill=INK)
        y += int(f.size * 1.28)

    _draw_source(d, source, m, avail)
    return img
