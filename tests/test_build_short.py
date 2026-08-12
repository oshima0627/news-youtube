import subprocess

import pytest
from PIL import Image

from scripts import build_short
from scripts.build_short import compose_stage
from scripts.cards import SHORT_SIZE

NARRATION = "レーダー照射は攻撃の一歩手前だと国会で答弁されています。" * 12

SCRIPT = {"headline": "中国軍機が照射", "narration": NARRATION,
          "subtitle": "照射は攻撃の一歩手前",
          "quote_excerpt": "攻撃の一歩手前",
          "figure_label": "照射回数", "figure_value": "1回",
          "title": "t", "tags": []}


def _photo(tmp_path, size=(1600, 900)):
    path = tmp_path / "photo.jpg"
    Image.new("RGB", size, (80, 90, 110)).save(path)
    return path


def test_下地は縦型の不透明画像になる(tmp_path):
    got = compose_stage(_photo(tmp_path), SCRIPT, source="国会会議録")
    assert got.size == SHORT_SIZE
    assert got.mode == "RGB"


def test_縦長の写真でも横幅いっぱいに収まる(tmp_path):
    photo = tmp_path / "tall.jpg"
    Image.new("RGB", (600, 1800), (10, 20, 30)).save(photo)

    got = compose_stage(photo, SCRIPT, source="e-Stat")
    assert got.size == SHORT_SIZE


# --- C1: figure の有無で根拠カードを出し分ける ----------------------------

def test_figureが空なら引用カードを使う(tmp_path, monkeypatch):
    # 発言系（Evidence.figure が空）でモデル生成の数値カードを使うと、
    # 捏造されうる値に一次資料の出典キャプションが付く。
    calls = []
    monkeypatch.setattr(build_short, "render_quote",
                        lambda text, source: (calls.append(("quote", text, source)),
                                              Image.new("RGB", (1080, 341)))[1])
    monkeypatch.setattr(build_short, "render_figure",
                        lambda *a: pytest.fail("figureが空なのに数値カードを使っている"))

    compose_stage(_photo(tmp_path), SCRIPT, source="国会会議録", figure="")

    assert calls == [("quote", "攻撃の一歩手前", "国会会議録")]


def test_figureがあれば数値カードを使う(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(build_short, "render_figure",
                        lambda label, value, source: (
                            calls.append(("figure", label, value, source)),
                            Image.new("RGB", (1080, 341)))[1])
    monkeypatch.setattr(build_short, "render_quote",
                        lambda *a: pytest.fail("figureがあるのに引用カードを使っている"))

    compose_stage(_photo(tmp_path), SCRIPT, source="e-Stat", figure="30%減")

    assert calls == [("figure", "照射回数", "1回", "e-Stat")]


# --- C2: 字幕バンドにはナレーション全文を渡さない --------------------------

def test_字幕バンドにはsubtitleを渡しナレーション全文は渡さない(tmp_path, monkeypatch):
    # 字幕バンドは4行（実測60文字あまり）しか描画しない。ナレーション全文
    # （350〜400字）を渡すと毎ビルド必ず切り捨て警告が出るうえ、画面には
    # 文の途中で切れた冒頭だけが60秒間出続ける。
    calls = []
    monkeypatch.setattr(build_short, "render_frame",
                        lambda headline, subtitle: (
                            calls.append((headline, subtitle)),
                            Image.new("RGBA", SHORT_SIZE, (0, 0, 0, 0)))[1])

    compose_stage(_photo(tmp_path), SCRIPT, source="国会会議録")

    assert calls == [("中国軍機が照射", "照射は攻撃の一歩手前")]
    assert NARRATION not in [c[1] for c in calls]


def test_実際のビルド経路で字幕の切り捨て警告が出ない(tmp_path, capsys):
    # モックせずに描画まで通し、「毎ビルド必ず出る警告」が消えたことを確認する。
    compose_stage(_photo(tmp_path), SCRIPT, source="第217回国会 予算委員会")
    out = capsys.readouterr().out
    assert "字幕が" not in out


def test_mp4_duration_secondsはffprobeの出力を秒数として返す(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="58.234000\n", stderr="")

    monkeypatch.setattr(build_short.subprocess, "run", fake_run)
    got = build_short.mp4_duration_seconds(tmp_path / "video.mp4")
    assert got == pytest.approx(58.234)


def test_mp4_duration_secondsはffprobe失敗時に原因つきの例外にする(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No such file")

    monkeypatch.setattr(build_short.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="No such file"):
        build_short.mp4_duration_seconds(tmp_path / "missing.mp4")


def test_verify_durationは範囲内なら警告を出さない(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_short, "mp4_duration_seconds", lambda p: 58.5)
    build_short.verify_duration(tmp_path / "video.mp4")
    assert "! 警告" not in capsys.readouterr().out


def test_verify_durationは範囲外なら警告を出す(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_short, "mp4_duration_seconds", lambda p: 63.0)
    build_short.verify_duration(tmp_path / "video.mp4")
    assert "! 警告" in capsys.readouterr().out


def test_verify_durationは範囲外でも例外にしない(tmp_path, monkeypatch):
    monkeypatch.setattr(build_short, "mp4_duration_seconds", lambda p: 30.0)
    got = build_short.verify_duration(tmp_path / "video.mp4")
    assert got == 30.0


def test_写真は上寄りで切り取る():
    # 人物のポートレート（縦長）を横長の写真枠に入れるので縦に大きく切り落とす。
    # 中央で切ると頭の上が欠ける（実測: 高市早苗・櫛渕万里・平口洋の公式
    # ポートレートで額から上が欠けた）。顔は上寄りにあるので上を残す。
    from PIL import Image

    from scripts.build_short import _fill

    src = Image.new("RGB", (100, 1000), (0, 0, 255))      # 下は青
    src.paste(Image.new("RGB", (100, 300), (255, 0, 0)), (0, 0))   # 上30%は赤

    got = _fill(src, (100, 100))

    # 中央で切っていれば青一色になる位置
    assert got.getpixel((50, 50)) == (255, 0, 0)


def test_写真の切り取り位置は指定できる():
    from PIL import Image

    from scripts.build_short import _fill

    src = Image.new("RGB", (100, 1000), (0, 0, 255))
    src.paste(Image.new("RGB", (100, 300), (255, 0, 0)), (0, 0))

    assert _fill(src, (100, 100), anchor_y=0.5).getpixel((50, 50)) == (0, 0, 255)
    assert _fill(src, (100, 100), anchor_y=0.0).getpixel((50, 50)) == (255, 0, 0)
