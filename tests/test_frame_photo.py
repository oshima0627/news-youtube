"""写真帯の縦横比に整えるヘルパのテスト。

狙いは1点: **_fill に切り取る余地を残さない**こと。余地が残ると、
もともとタイトに切り抜かれた顔写真で頭頂とあごが窓の外に出る
（2026-09-02 に古謝玄太の記事画像 550x733 で実際に起きた）。
"""
from PIL import Image

from scripts.build_short import _fill
from scripts.cards import PHOTO_H, SHORT_SIZE
from scripts.frame_photo import frame_to_aspect

BAND = (SHORT_SIZE[0], PHOTO_H)


def test_縦長の写真は帯と同じ比率になる():
    got = frame_to_aspect(Image.new("RGB", (550, 733), (10, 20, 30)), BAND)
    assert abs(got.width / got.height - BAND[0] / BAND[1]) < 0.01


def test_整えたあとは_fill_が縦を切り落とさない():
    # 元画像の高さがそのまま残っていれば、頭頂もあごも窓の中に入る。
    src = Image.new("RGB", (550, 733), (10, 20, 30))
    framed = frame_to_aspect(src, BAND)
    assert framed.height == src.height
    filled = _fill(framed, BAND)
    assert filled.size == BAND


def test_前景は中央に置かれ元の絵がそのまま残る():
    src = Image.new("RGB", (550, 733), (255, 0, 0))
    framed = frame_to_aspect(src, BAND)
    cx, cy = framed.width // 2, framed.height // 2
    assert framed.getpixel((cx, cy)) == (255, 0, 0)
    # 左右の端は元画像の外側＝ぼかし背景なので、前景がそこまで伸びていない
    assert framed.width > src.width


def test_すでに横長なら何もしない():
    src = Image.new("RGB", (1600, 900), (1, 2, 3))
    got = frame_to_aspect(src, BAND)
    assert got.size == src.size
