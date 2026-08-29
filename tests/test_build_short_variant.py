"""TikTok バリアント（work/<id>/tiktok/）を同じ build_short で作るための
パラメータ化のテスト。

写真・ライセンス・レシピは題材ごとに1つで、YouTube 版と共有する。台本・音声・
テロップ・mp4 だけがバリアント側にある。取り違えると「別の題材の写真に別の
題材の原稿が乗る」ので、解決先を1つの関数に閉じ込めて縛る。
"""

from __future__ import annotations

from pathlib import Path

from scripts import build_short


def test_既定では素材もレシピもworkdir自身から取る():
    src = build_short.resolve_sources(Path("work/abc123"))
    assert src.photo == Path("work/abc123/photo.jpg")
    assert src.license == Path("work/abc123/license.json")
    assert src.recipe.name == "abc123.json"


def test_バリアントは素材を親から_レシピを題材IDから取る():
    src = build_short.resolve_sources(
        Path("work/abc123/tiktok"),
        assets_dir=Path("work/abc123"), recipe_id="abc123")
    assert src.photo == Path("work/abc123/photo.jpg")
    assert src.license == Path("work/abc123/license.json")
    assert src.recipe.name == "abc123.json"


def test_バリアントでも台本は自分のディレクトリから取る():
    src = build_short.resolve_sources(
        Path("work/abc123/tiktok"),
        assets_dir=Path("work/abc123"), recipe_id="abc123")
    assert src.script == Path("work/abc123/tiktok/script.json")
    assert src.voice == Path("work/abc123/tiktok/voice.wav")
    assert src.out == Path("work/abc123/tiktok/video.mp4")


def test_verify_durationは渡した窓で判定する(tmp_path, monkeypatch, capsys):
    """TikTok の 68〜80秒は、ショートの既定窓では毎回「範囲外」になる。
    窓を渡せなければ本物の異常がその警告に埋もれる。"""
    monkeypatch.setattr(build_short, "mp4_duration_seconds", lambda p: 74.0)
    build_short.verify_duration(tmp_path / "v.mp4",
                                target_min=68.0, target_max=80.0)
    assert "警告" not in capsys.readouterr().out


def test_verify_durationは渡した窓の外なら警告を出す(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_short, "mp4_duration_seconds", lambda p: 58.5)
    build_short.verify_duration(tmp_path / "v.mp4",
                                target_min=68.0, target_max=80.0)
    assert "警告" in capsys.readouterr().out


def test_verify_durationの既定はショートの窓のまま(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_short, "mp4_duration_seconds", lambda p: 58.5)
    build_short.verify_duration(tmp_path / "v.mp4")
    assert "警告" not in capsys.readouterr().out
