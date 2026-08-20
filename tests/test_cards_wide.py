"""16:9（長尺）の描画。

ショート（cards.py）と分けてある理由は
docs/superpowers/specs/2026-08-20-long-form-design.md を参照。
"""

from scripts.cards_wide import (BODY_H, BODY_TOP, CARD_W, HEADLINE_H, PHOTO_W,
                                TELOP_H, TELOP_TOP, WIDE_SIZE, render_contents,
                                render_headline, render_quote, render_telop)
from scripts.draw import NAVY, ORANGE


def _ink_bbox(img):
    """地色（濃紺）以外が描かれている範囲。枠からのはみ出しを見る。"""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(img.convert("RGB"),
                                 Image.new("RGB", img.size, NAVY))
    return diff.getbbox()


# --- 版面 -------------------------------------------------------------------

def test_長尺は1920x1080で組む():
    assert WIDE_SIZE == (1920, 1080)


def test_帯を積むと画面ちょうどに収まる():
    # 縦に隙間や食い違いがあると、連結したときにその帯だけ地色が覗く。
    assert HEADLINE_H < BODY_TOP + BODY_H == TELOP_TOP
    assert TELOP_TOP + TELOP_H == WIDE_SIZE[1]


def test_実写と引用カードは左右に並んで画面幅に収まる():
    # 縦型の積み上げをそのまま横に伸ばすと写真が間延びする。
    assert PHOTO_W + CARD_W < WIDE_SIZE[0]


def test_各要素は決められた大きさで返る():
    assert render_headline("見出し", 1).size == (WIDE_SIZE[0], HEADLINE_H)
    assert render_telop("テロップ").size == (WIDE_SIZE[0], TELOP_H)
    assert render_quote("十二文字以上ある逐語引用です", "国会会議録").size == (CARD_W, BODY_H)
    assert render_contents(["ア", "イ", "ウ"]).size == (WIDE_SIZE[0], BODY_H)


# --- 見出し -----------------------------------------------------------------

def test_見出しに章番号が入る():
    # 章で区切るまとめ形式なので、いま何番目を見ているかを画面に出す。
    from PIL import ImageChops, Image
    with_number = render_headline("同じ見出し", 2)
    without = render_headline("同じ見出し", 0)

    assert ImageChops.difference(with_number.convert("RGB"),
                                 without.convert("RGB")).getbbox() is not None


def test_長い見出しでも帯からはみ出さない():
    box = _ink_bbox(render_headline("あ" * 120, 1))

    assert box is not None
    assert box[3] <= HEADLINE_H


# --- テロップ ---------------------------------------------------------------

def test_テロップはオレンジで描く():
    img = render_telop("イタリアは基本的な食料品は4%ですが").convert("RGB")
    colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}

    assert ORANGE in colors
    assert not any(c[0] > 200 and c[1] > 200 and c[2] > 200 for c in colors)


def test_長いテロップでも帯からはみ出さない():
    box = _ink_bbox(render_telop("あ" * 200))

    assert box is not None
    assert box[3] <= TELOP_H


# --- 引用カード -------------------------------------------------------------

def test_引用カードは漢数字を算用数字に直して描く():
    # 国会会議録は数字を漢字で書き起こす。表記だけ変えて値は変えない。
    from PIL import ImageChops
    kanji = render_quote("一〇％の引用がここにあります", "国会会議録")
    arabic = render_quote("10%の引用がここにあります", "国会会議録")

    assert ImageChops.difference(kanji.convert("RGB"),
                                 arabic.convert("RGB")).getbbox() is None


def test_長い引用でもカードからはみ出さない():
    box = _ink_bbox(render_quote("あ" * 300, "国会会議録"))

    assert box is not None
    assert box[2] <= CARD_W and box[3] <= BODY_H


def test_長い出典でもカードからはみ出さない():
    # 出典は会議名＋日付＋発言者なので長くなりやすい。
    box = _ink_bbox(render_quote("十二文字以上ある逐語引用です", "参議院" * 40))

    assert box is not None
    assert box[2] <= CARD_W and box[3] <= BODY_H


# --- 目次面 -----------------------------------------------------------------

def test_目次面は3題材の見出しを並べる():
    from PIL import ImageChops
    three = render_contents(["アイウ", "エオカ", "キクケ"])
    two = render_contents(["アイウ", "エオカ"])

    assert ImageChops.difference(three.convert("RGB"),
                                 two.convert("RGB")).getbbox() is not None


def test_長い見出しを並べても目次面からはみ出さない():
    box = _ink_bbox(render_contents(["あ" * 60] * 3))

    assert box is not None
    assert box[3] <= BODY_H


def test_引用が行数を超えると警告が出る(capsys):
    render_quote("あ" * 300, "国会会議録")
    out = capsys.readouterr().out
    assert "引用" in out and "切り捨て" in out


def test_引用が長くても出典は必ず描かれる(capsys):
    # 出典が押し出されると「一次資料の裏づけが画面から消えた引用カード」に
    # なる。引用のほうを切って、出典は必ず残す。
    from PIL import Image, ImageChops
    img = render_quote("あ" * 300, "参議院予算委員会 2026年6月16日 片山さつき")
    bottom = img.crop((0, BODY_H - 130, CARD_W, BODY_H))
    diff = ImageChops.difference(bottom.convert("RGB"),
                                 Image.new("RGB", bottom.size, NAVY))

    assert diff.getbbox() is not None
