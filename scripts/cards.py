#!/usr/bin/env python3
"""縦型ショートの描画。

  0〜340      見出し（2行まで。帯に収まる範囲でいちばん大きく）
  340〜1080   実写
  1080〜1360  テロップ（読み上げに同期して切り替わる。オレンジ）
  1360〜1701  根拠カード（数値カード or 引用カード）
  1701〜1920  空け

**テロップは写真のすぐ下、根拠カードはその下。** 目線が上から
「見出し → 顔 → いま読んでいる言葉 → その根拠」と自然に降りる並びにしている。

**下端260pxは何も置かない。** Shorts の再生画面ではチャンネル名・タイトル・
ボタン類が下から重なるので、そこに文字を置くと隠れる。

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

from scripts.draw import (INK, MUTED, NAVY, ORANGE, RED, fit_font, fit_wrapped,
                           normalize_numerals, pick_font, truncate_ellipsis,
                           wrap)

SHORT_SIZE = (1080, 1920)
HEADLINE_H = 340          # 見出しの帯
PHOTO_TOP = HEADLINE_H
PHOTO_H = 740             # 実写
TELOP_TOP = PHOTO_TOP + PHOTO_H
TELOP_H = 280             # テロップ
CARD_TOP = TELOP_TOP + TELOP_H
CARD_H = 341              # 根拠カード
# CARD_TOP + CARD_H = 1701。以降 219px は Shorts のUIに隠れるので空ける。

MARGIN = int(SHORT_SIZE[0] * 0.06)
AVAIL = SHORT_SIZE[0] - MARGIN * 2


HEADLINE_MAX_LINES = 2
TELOP_MAX_LINES = 3


def render_headline(headline: str) -> Image.Image:
    """見出しの帯。**画面で一番強い要素にする。**

    サムネイル代わりに一瞬で内容を伝える場所なので、本文より一段大きく、
    太い縁取りを付ける。左のオレンジの帯は見出しの始まりを示す目印で、
    テロップの色とそろえてある。
    """
    img = Image.new("RGB", (SHORT_SIZE[0], HEADLINE_H), NAVY)
    d = ImageDraw.Draw(img)

    # 帯に収まる範囲でいちばん大きくする。短い見出しほど大きくなり、
    # 一瞬で内容が伝わる。
    f, lines = fit_wrapped(d, headline, AVAIL - 40, HEADLINE_H - 56,
                           HEADLINE_MAX_LINES, start=150, minimum=52)
    if len(lines) > HEADLINE_MAX_LINES:
        print(f"! 見出しが{len(lines) - HEADLINE_MAX_LINES}行溢れて"
              f"切り捨てられました: {headline[:20]}")
    lines = lines[:HEADLINE_MAX_LINES]

    step = int(f.size * 1.22)
    block = step * len(lines)
    y = max(24, (HEADLINE_H - block) // 2)      # 帯の中で縦に中央寄せ

    # 見出しの左に立てるオレンジの縦帯
    d.rectangle([MARGIN, y + 12, MARGIN + 14, y + block - 12], fill=ORANGE)

    for line in lines:
        x = MARGIN + 40
        d.text((x, y), line, font=f, fill=INK,
               stroke_width=10, stroke_fill=(0, 0, 0))
        d.text((x, y), line, font=f, fill=INK)
        y += step
    return img


def render_telop(text: str) -> Image.Image:
    """テロップ。写真のすぐ下に出す、いま読み上げている言葉。

    色は白ではなくオレンジにする。引用カードの文字（白）と同じ色だと、
    どちらが「いま読んでいる所」なのか見分けがつかない。
    """
    img = Image.new("RGB", (SHORT_SIZE[0], TELOP_H), NAVY)
    d = ImageDraw.Draw(img)

    size = 66
    f = pick_font(size)
    lines = wrap(d, text, f, AVAIL)
    while len(lines) > TELOP_MAX_LINES and size > 40:
        size -= 4
        f = pick_font(size)
        lines = wrap(d, text, f, AVAIL)
    if len(lines) > TELOP_MAX_LINES:
        print(f"! テロップが{len(lines) - TELOP_MAX_LINES}行溢れて"
              f"切り捨てられました: {text[:20]}")
    lines = lines[:TELOP_MAX_LINES]

    step = int(f.size * 1.24)
    y = max(24, (TELOP_H - step * len(lines)) // 2)
    for line in lines:
        d.text((MARGIN, y), line, font=f, fill=ORANGE,
               stroke_width=5, stroke_fill=(0, 0, 0))
        d.text((MARGIN, y), line, font=f, fill=ORANGE)
        y += step
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
    y = CARD_H - 56 - (len(shown) - 1) * 40
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
    img = Image.new("RGB", (w, CARD_H), NAVY)
    d = ImageDraw.Draw(img)
    m = MARGIN
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

    漢数字は算用数字に直して描く（「一〇％」→「10%」）。国会会議録は数字を
    漢字で書き起こすため、そのまま出すと読みづらい。**表記だけを変えて値は
    変えない**変換で、逐語であることの検証（run_daily.ensure_grounded_card）は
    変換前の文字列に対して済んでいる。
    """
    text = normalize_numerals(text)
    w = SHORT_SIZE[0]
    img = Image.new("RGB", (w, CARD_H), NAVY)
    d = ImageDraw.Draw(img)
    m = MARGIN
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
