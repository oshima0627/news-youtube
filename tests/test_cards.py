from scripts.cards import (HOLE_BOTTOM, HOLE_TOP, SHORT_SIZE, render_figure,
                           render_frame)


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
    assert img.size[1] == HOLE_BOTTOM - (HOLE_TOP + 659)


def test_長い見出しでも帯からはみ出さない():
    # 折り返して2行に切るので、帯の外に文字が出てはいけない
    img = render_frame("あ" * 60, "い" * 80)
    w, _ = SHORT_SIZE
    # 穴の中央に文字が漏れていない（＝透過のまま）
    assert img.getpixel((w // 2, (HOLE_TOP + HOLE_BOTTOM) // 2))[3] == 0
    assert img.size == SHORT_SIZE
