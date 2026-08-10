from PIL import Image, ImageDraw

from scripts import draw as draw_module
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


def test_日本語フォントが全滅したら警告を出す(monkeypatch, capsys):
    # 警告が無いと、文字がすべて豆腐（□）になった動画が完全自動で
    # そのまま公開され、誰も気づかない
    monkeypatch.setattr(draw_module, "FONT_SANS", [r"C:\存在しない\font.ttc"])
    monkeypatch.setattr(draw_module, "_warned_no_font", False)

    pick_font(40)

    out = capsys.readouterr().out
    assert "日本語フォント" in out
    assert "豆腐" in out


def test_フォント全滅の警告は一度しか出さない(monkeypatch, capsys):
    # pick_font は1フレームあたり何十回も呼ばれる。毎回出すと他の警告が埋もれる
    monkeypatch.setattr(draw_module, "FONT_SANS", [r"C:\存在しない\font.ttc"])
    monkeypatch.setattr(draw_module, "_warned_no_font", False)

    for _ in range(5):
        pick_font(40)

    assert capsys.readouterr().out.count("日本語フォント") == 1
