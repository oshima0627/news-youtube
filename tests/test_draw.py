from PIL import Image, ImageDraw

from scripts.draw import fit_font, pick_font, wrap


def _draw():
    return ImageDraw.Draw(Image.new("RGB", (10, 10)))


def test_wrapは改行を空白に正規化してから折り返す():
    # textbboxは\nを含む文字列を複数行として測定するため、正規化しないと
    # 幅の判定がズレる。改行入りと、事前に空白へ置換したものとで
    # 同じ折り返し結果になることを確認する。
    d = _draw()
    f = pick_font(40)
    with_newline = wrap(d, "あいう\nえお", f, 10_000)
    pre_normalized = wrap(d, "あいう えお", f, 10_000)
    assert with_newline == pre_normalized


def test_fit_fontは改行を空白に正規化してから幅を測る():
    d = _draw()
    with_newline = fit_font(d, "あ\nい", 200, 92)
    pre_normalized = fit_font(d, "あ い", 200, 92)
    assert with_newline.size == pre_normalized.size
