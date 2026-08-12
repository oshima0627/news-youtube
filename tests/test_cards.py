from scripts.cards import (CARD_H, CARD_TOP, HEADLINE_H, SHORT_SIZE, TELOP_H,
                           TELOP_TOP, render_figure, render_headline,
                           render_quote, render_telop)
from scripts.draw import NAVY, ORANGE


def _ink_bbox(img):
    """地色（濃紺）以外が描かれている範囲。帯からのはみ出しを見る。"""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(img.convert("RGB"),
                                 Image.new("RGB", img.size, NAVY))
    return diff.getbbox()


# --- 帯の大きさ -------------------------------------------------------------

def test_各帯は決められた高さで返る():
    assert render_headline("見出し").size == (SHORT_SIZE[0], HEADLINE_H)
    assert render_telop("テロップ").size == (SHORT_SIZE[0], TELOP_H)
    assert render_figure("削減数", "45", "国会会議録").size == (SHORT_SIZE[0], CARD_H)
    assert render_quote("十二文字以上ある逐語引用です", "国会会議録").size == (SHORT_SIZE[0], CARD_H)


def test_帯を積むと下端に余白が残る():
    # Shorts の再生画面ではチャンネル名・タイトル・ボタンが下から重なる。
    # そこに文字を置くと隠れるので、下端は空けておく。
    assert CARD_TOP + CARD_H <= SHORT_SIZE[1] - 200


def test_テロップは写真のすぐ下で根拠カードより上にある():
    # 目線が「見出し → 顔 → いま読んでいる言葉 → その根拠」と降りる並び。
    assert HEADLINE_H < TELOP_TOP < CARD_TOP
    assert TELOP_TOP + TELOP_H == CARD_TOP


# --- テロップ ---------------------------------------------------------------

def test_テロップはオレンジで描く():
    # 引用カードの文字（白）と同じ色だと、どちらが「いま読んでいる所」か
    # 見分けがつかない。
    img = render_telop("イタリアは基本的な食料品は4%ですが").convert("RGB")
    colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}

    assert ORANGE in colors
    assert not any(c[0] > 200 and c[1] > 200 and c[2] > 200 for c in colors)


def test_長いテロップでも帯からはみ出さない():
    img = render_telop("あ" * 200)
    box = _ink_bbox(img)

    assert box is not None
    assert box[3] <= TELOP_H


def test_テロップが行数を超えると警告が出る(capsys):
    render_telop("あ" * 200)
    out = capsys.readouterr().out
    assert "テロップ" in out
    assert "切り捨て" in out


def test_短いテロップでは警告が出ない(capsys):
    render_telop("短いテロップです")
    assert capsys.readouterr().out == ""


# --- 見出し -----------------------------------------------------------------

def test_長い見出しでも帯からはみ出さない():
    img = render_headline("あ" * 60)
    box = _ink_bbox(img)

    assert box is not None
    assert box[3] <= HEADLINE_H


def test_見出しが2行を超えると警告が出る(capsys):
    render_headline("あ" * 60)
    out = capsys.readouterr().out
    assert "見出し" in out
    assert "切り捨て" in out


def test_短い見出しでは警告が出ない(capsys):
    render_headline("短い見出し")
    assert capsys.readouterr().out == ""


def test_見出しにはオレンジの目印が入る():
    img = render_headline("食料品の軽減税率").convert("RGB")
    colors = {c for _, c in img.getcolors(maxcolors=1 << 20)}

    assert ORANGE in colors


def test_出典が長いと折り返した上で警告が出る(capsys):
    img = render_figure("削減数", "45", "参議院予算委員会 2026年8月1日 山田太郎議員の質疑" * 3)
    out = capsys.readouterr().out
    assert "出典" in out
    assert "切り捨て" in out
    # 折り返し後もカード幅・高さは変わらない
    assert img.size[0] == SHORT_SIZE[0]
    assert img.size[1] == CARD_H


def test_数値が極端に長いと省略記号で切り詰められ警告が出る(capsys):
    render_figure("削減数", "1" * 200, "国会会議録")
    out = capsys.readouterr().out
    assert "数値" in out
    assert "切り詰め" in out


# --- 引用カード（一次資料が発言のとき使う） --------------------------------

def test_引用カードは数値カードと同じ大きさで返る():
    # compose_stage が穴の下側にそのまま貼るので、数値カードと同寸でないと
    # 隙間やはみ出しが出る
    img = render_quote("議員定数を四十五削減する", "第217回国会 予算委員会")
    assert img.size[0] == SHORT_SIZE[0]
    assert img.size[1] == CARD_H


def test_引用カードは25文字の引用でも警告なしに収まる(capsys):
    # quote_excerpt の上限は25文字。上限ちょうどで切り捨てが起きてはいけない
    render_quote("あ" * 25, "第217回国会 衆議院予算委員会 2025-11-20 野田佳彦")
    out = capsys.readouterr().out
    assert "引用が" not in out


def test_引用カードは出典キャプションを持つ(capsys):
    # 出典が長ければ数値カードと同じ流儀で折り返し＋警告になる
    render_quote("短い引用", "参議院予算委員会 2026年8月1日 山田太郎議員の質疑" * 3)
    out = capsys.readouterr().out
    assert "出典" in out
    assert "切り捨て" in out


def test_引用カードは漢数字を算用数字で描く():
    # 国会会議録は「一〇％」と書き起こす。そのまま出すと読めないので
    # 描画の直前に表記を直す。同じ内容なら描かれる絵も同じになるはず。
    from scripts.cards import render_quote

    src = "第221回国会 参議院財政金融委員会 2026-06-16 片山さつき"
    kanji = render_quote("肉、魚は一〇％なんですよ", src)
    arabic = render_quote("肉、魚は10%なんですよ", src)

    assert kanji.tobytes() == arabic.tobytes()


def test_引用カードは命数法も読みやすく描く():
    from scripts.cards import render_quote

    src = "第217回国会 参議院内閣委員会 2025-04-15 谷滋行"
    kanji = render_quote("詐欺被害が千六百三十億円に上り", src)
    arabic = render_quote("詐欺被害が1630億円に上り", src)

    assert kanji.tobytes() == arabic.tobytes()
