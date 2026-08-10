#!/usr/bin/env python3
"""縦型ショートの描画。

  上部の帯   見出し（2行まで）
  中央の穴   上に実写、下に数値カード
  下部の帯   ナレーションの要点を字幕で

数値カードが「解説」の実体になる。これが無いと画像スライドショーと
見分けがつかず、量産型コンテンツの判定に近づく。
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


def render_figure(label: str, value: str, source: str) -> Image.Image:
    """数値カード。穴の下側にぴったり収まる大きさで返す。

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

    sf = pick_font(34)
    max_source_lines = 2
    source_lines = wrap(d, f"出典: {source}", sf, avail)
    if len(source_lines) > max_source_lines:
        print(f"! 出典が{len(source_lines) - max_source_lines}行溢れて切り捨てられました: {source[:20]}")
    shown = source_lines[:max_source_lines]
    y = FIGURE_H - 56 - (len(shown) - 1) * 40
    for ln in shown:
        d.text((m, y), ln, font=sf, fill=MUTED)
        y += 40
    return img
