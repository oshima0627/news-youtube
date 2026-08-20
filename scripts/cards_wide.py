#!/usr/bin/env python3
"""長尺（16:9）の描画。

    0〜180      見出し（章番号つき）
  180〜900      実写（左）＋ 引用カード（右）
  900〜1080     テロップ（読み上げに同期して切り替わる。オレンジ）

**縦型（cards.py）をそのまま横に伸ばさない。** 1920x1080 に縦積みすると
実写の帯が横長になりすぎて人物が間延びし、引用カードは1行あたりの文字数が
増えて読点まで目が届かなくなる。左右に分けて、実写と根拠を同時に見せる。

導入と結びのパートでは、実写と引用カードの代わりに**目次面**
（render_contents）を出す。この2パートは特定の一次資料に紐づかないので、
一次資料の出典キャプションが付いた要素を画面に出さない。

カードに出す文字列が一次資料に由来していなければならないことは
ショートと同じ（cards.py の冒頭を参照）。逐語であることの検証は
`build_long.compose_segment()` が描画直前に通す。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from scripts.draw import (INK, MUTED, NAVY, ORANGE, RED, fit_wrapped,
                          normalize_numerals, pick_font, wrap)

WIDE_SIZE = (1920, 1080)

HEADLINE_H = 180          # 見出しの帯
BODY_TOP = HEADLINE_H
BODY_H = 720              # 実写と引用カードが並ぶ段
TELOP_TOP = BODY_TOP + BODY_H
TELOP_H = 180             # テロップ
# TELOP_TOP + TELOP_H = 1080。長尺は Shorts のUIに隠れないので下端まで使う。

MARGIN = 60
GAP = 40                  # 実写と引用カードの間
PHOTO_W = 780
CARD_W = WIDE_SIZE[0] - MARGIN * 2 - GAP - PHOTO_W   # 980
PHOTO_LEFT = MARGIN
CARD_LEFT = MARGIN + PHOTO_W + GAP

HEADLINE_MAX_LINES = 2
TELOP_MAX_LINES = 2
QUOTE_MAX_LINES = 6
SOURCE_MAX_LINES = 3
CONTENTS_MAX_LINES = 2    # 目次1件あたり

# 章番号のバッジ（見出しの左）
BADGE_W = 96


def render_headline(headline: str, number: int = 0) -> Image.Image:
    """見出しの帯。`number` が1以上なら章番号のバッジを左に置く。

    まとめ形式では画面が3回切り替わるので、**いま何番目を見ているか**が
    分からないと、視聴者は前の題材の話が続いていると受け取る。
    導入・結び（number=0）はバッジを出さない。
    """
    img = Image.new("RGB", (WIDE_SIZE[0], HEADLINE_H), NAVY)
    d = ImageDraw.Draw(img)

    left = MARGIN
    if number > 0:
        d.rectangle([left, 34, left + BADGE_W, HEADLINE_H - 34], fill=ORANGE)
        nf = pick_font(72)
        nb = d.textbbox((0, 0), str(number), font=nf)
        d.text((left + (BADGE_W - (nb[2] - nb[0])) // 2 - nb[0],
                (HEADLINE_H - (nb[3] - nb[1])) // 2 - nb[1]),
               str(number), font=nf, fill=NAVY)
        left += BADGE_W + 28
    else:
        d.rectangle([left, 34, left + 14, HEADLINE_H - 34], fill=ORANGE)
        left += 40

    avail = WIDE_SIZE[0] - left - MARGIN
    f, lines = fit_wrapped(d, headline, avail, HEADLINE_H - 36,
                           HEADLINE_MAX_LINES, start=88, minimum=40)
    if len(lines) > HEADLINE_MAX_LINES:
        print(f"! 見出しが{len(lines) - HEADLINE_MAX_LINES}行溢れて"
              f"切り捨てられました: {headline[:20]}")
    lines = lines[:HEADLINE_MAX_LINES]

    step = int(f.size * 1.20)
    y = max(16, (HEADLINE_H - step * len(lines)) // 2)
    for line in lines:
        d.text((left, y), line, font=f, fill=INK,
               stroke_width=8, stroke_fill=(0, 0, 0))
        d.text((left, y), line, font=f, fill=INK)
        y += step
    return img


def render_telop(text: str) -> Image.Image:
    """テロップ。いま読み上げている言葉。色はショートと同じオレンジ。"""
    img = Image.new("RGB", (WIDE_SIZE[0], TELOP_H), NAVY)
    d = ImageDraw.Draw(img)

    avail = WIDE_SIZE[0] - MARGIN * 2
    size = 62
    f = pick_font(size)
    lines = wrap(d, text, f, avail)
    while len(lines) > TELOP_MAX_LINES and size > 40:
        size -= 4
        f = pick_font(size)
        lines = wrap(d, text, f, avail)
    if len(lines) > TELOP_MAX_LINES:
        print(f"! テロップが{len(lines) - TELOP_MAX_LINES}行溢れて"
              f"切り捨てられました: {text[:20]}")
    lines = lines[:TELOP_MAX_LINES]

    step = int(f.size * 1.24)
    y = max(14, (TELOP_H - step * len(lines)) // 2)
    for line in lines:
        d.text((MARGIN, y), line, font=f, fill=ORANGE,
               stroke_width=5, stroke_fill=(0, 0, 0))
        d.text((MARGIN, y), line, font=f, fill=ORANGE)
        y += step
    return img


def render_quote(text: str, source: str) -> Image.Image:
    """引用カード。実写の右に置く、逐語引用と出典。

    ショート（cards.py の 1080x341）より縦に広いので行数を増やせる。
    引用が長いほど文脈が伝わるが、6行を超える引用は読み切る前に画面が
    変わるので、そこで切って警告する。

    漢数字は算用数字に直して描く（「一〇％」→「10%」）。表記だけを変えて
    値は変えない変換で、逐語であることの検証は変換前の文字列に対して
    済んでいる（build_long.compose_segment）。
    """
    text = normalize_numerals(text)
    img = Image.new("RGB", (CARD_W, BODY_H), NAVY)
    d = ImageDraw.Draw(img)
    m = 44
    avail = CARD_W - m * 2

    d.rectangle([0, 0, CARD_W, 8], fill=RED)
    d.text((m, 34), "一次資料より", font=pick_font(34), fill=MUTED)

    # 出典を先に置いて、引用に使える高さを決める。逆にすると長い引用が
    # 出典を押し出し、**出典の無い引用カード**が出る（一次資料の裏づけが
    # 画面から消える）。
    sf = pick_font(30)
    source_lines = wrap(d, f"出典: {source}", sf, avail)
    if len(source_lines) > SOURCE_MAX_LINES:
        print(f"! 出典が{len(source_lines) - SOURCE_MAX_LINES}行溢れて"
              f"切り捨てられました: {source[:20]}")
    source_lines = source_lines[:SOURCE_MAX_LINES]
    source_h = 40 * len(source_lines)
    source_top = BODY_H - 40 - source_h

    body = f"「{text}」"
    top = 96
    room = source_top - 24 - top
    size = 54
    f = pick_font(size)
    lines = wrap(d, body, f, avail)
    while size > 32 and (len(lines) > QUOTE_MAX_LINES
                         or int(f.size * 1.34) * len(lines) > room):
        size -= 3
        f = pick_font(size)
        lines = wrap(d, body, f, avail)

    step = int(f.size * 1.34)
    fits = max(1, min(QUOTE_MAX_LINES, room // step))
    if len(lines) > fits:
        print(f"! 引用が{len(lines) - fits}行溢れて切り捨てられました: {text[:20]}")
    # 引用が短いとカードの下半分が丸ごと空く。使える高さの中で縦に中央寄せする。
    shown = lines[:fits]
    y = top + max(0, (room - step * len(shown)) // 2)
    for ln in shown:
        d.text((m, y), ln, font=f, fill=INK)
        y += step

    y = source_top
    for ln in source_lines:
        d.text((m, y), ln, font=sf, fill=MUTED)
        y += 40
    return img


def render_contents(headlines: list[str]) -> Image.Image:
    """目次面。導入と結びで出す、その回に扱う題材の一覧。

    導入・結びは特定の一次資料に紐づかないパートなので、実写や引用カード
    （出典キャプションが付く要素）は置かない。画面に出るのは、これから
    各章で扱う見出しそのものだけになる。
    """
    img = Image.new("RGB", (WIDE_SIZE[0], BODY_H), NAVY)
    d = ImageDraw.Draw(img)

    # 見出し帯に「きょうの論点」が出ているので、ここには小見出しを置かない
    # （同じ文字列が画面に2つ並ぶ）。
    m = MARGIN + 40
    avail = WIDE_SIZE[0] - m - MARGIN * 2

    y = 60
    room = (BODY_H - y - 40) // max(1, len(headlines))
    for i, headline in enumerate(headlines, start=1):
        f, lines = fit_wrapped(d, headline, avail - BADGE_W - 28,
                               room - 24, CONTENTS_MAX_LINES,
                               start=62, minimum=32)
        if len(lines) > CONTENTS_MAX_LINES:
            print(f"! 目次の見出しが{len(lines) - CONTENTS_MAX_LINES}行溢れて"
                  f"切り捨てられました: {headline[:20]}")
        lines = lines[:CONTENTS_MAX_LINES]

        d.rectangle([m, y + 6, m + 12, y + 6 + f.size], fill=ORANGE)
        nf = pick_font(int(f.size * 0.9))
        d.text((m + 34, y), f"{i}", font=nf, fill=ORANGE)

        step = int(f.size * 1.22)
        ty = y
        for line in lines:
            d.text((m + 34 + BADGE_W, ty), line, font=f, fill=INK)
            ty += step
        y += room
    return img
