from scripts.cards import (HOLE_BOTTOM, HOLE_TOP, PHOTO_H, SHORT_SIZE,
                           render_figure, render_frame)


def _hole_is_fully_transparent(img):
    """穴の領域(HOLE_TOP〜HOLE_BOTTOM)全体に不透明ピクセルが無いか。

    帯の文字が穴に侵入していない＝はみ出していない、という検証になる。
    crop + alpha.getbbox() はPillow内部でCループとして走るので、
    1ピクセルずつgetpixel()で回すより十分速い。
    """
    w, _ = SHORT_SIZE
    hole = img.crop((0, HOLE_TOP, w, HOLE_BOTTOM))
    alpha = hole.split()[3]
    return alpha.getbbox() is None


def test_フレームは縦型で中央が透過している():
    img = render_frame("中国軍機が照射", "レーダー照射は攻撃の一歩手前")
    assert img.size == SHORT_SIZE
    assert img.mode == "RGBA"

    w, _ = SHORT_SIZE
    # 上下の帯は不透明、中央の穴は透過
    assert img.getpixel((w // 2, HOLE_TOP - 20))[3] == 255
    assert img.getpixel((w // 2, (HOLE_TOP + HOLE_BOTTOM) // 2))[3] == 0
    assert img.getpixel((w // 2, HOLE_BOTTOM + 20))[3] == 255


def test_数値カードは穴の下側の大きさで返る():
    img = render_figure("削減数", "45", "国会会議録")
    assert img.size[0] == SHORT_SIZE[0]
    assert img.size[1] == HOLE_BOTTOM - (HOLE_TOP + PHOTO_H)


def test_長い見出しでも帯からはみ出さない():
    # 折り返して2行/4行に切るので、帯の外（穴の中）に文字が出てはいけない。
    # 穴全体を走査して不透明ピクセルが1つも無いことを確認する
    # （中心1点だけでは、たまたま小さいフォントが選ばれて通っただけ、
    #   という偽陰性を見逃す）。見出し・字幕の両方を極端に長くして確認する。
    img = render_frame("あ" * 60, "い" * 80)
    assert img.size == SHORT_SIZE
    assert _hole_is_fully_transparent(img)


def test_見出しが2行を超えると警告が出る(capsys):
    render_frame("あ" * 60, "普通の字幕")
    out = capsys.readouterr().out
    assert "見出し" in out
    assert "切り捨て" in out


def test_字幕が4行を超えると警告が出る(capsys):
    render_frame("普通の見出し", "い" * 80)
    out = capsys.readouterr().out
    assert "字幕" in out
    assert "切り捨て" in out


def test_見出しと字幕が短ければ警告は出ない(capsys):
    render_frame("短い見出し", "短い字幕")
    out = capsys.readouterr().out
    assert out == ""


def test_出典が長いと折り返した上で警告が出る(capsys):
    img = render_figure("削減数", "45", "参議院予算委員会 2026年8月1日 山田太郎議員の質疑" * 3)
    out = capsys.readouterr().out
    assert "出典" in out
    assert "切り捨て" in out
    # 折り返し後もカード幅・高さは変わらない
    assert img.size[0] == SHORT_SIZE[0]
    assert img.size[1] == HOLE_BOTTOM - (HOLE_TOP + PHOTO_H)


def test_数値が極端に長いと省略記号で切り詰められ警告が出る(capsys):
    render_figure("削減数", "1" * 200, "国会会議録")
    out = capsys.readouterr().out
    assert "数値" in out
    assert "切り詰め" in out
