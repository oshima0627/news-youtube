import subprocess

import pytest
from PIL import Image

from scripts import build_short
from scripts.build_short import compose_stage
from scripts.cards import SHORT_SIZE

SCRIPT = {"headline": "中国軍機が照射", "narration": "レーダー照射は攻撃の一歩手前",
          "figure_label": "照射回数", "figure_value": "1回",
          "title": "t", "tags": []}


def test_下地は縦型の不透明画像になる(tmp_path):
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (1600, 900), (80, 90, 110)).save(photo)

    got = compose_stage(photo, SCRIPT, source="国会会議録")
    assert got.size == SHORT_SIZE
    assert got.mode == "RGB"


def test_縦長の写真でも横幅いっぱいに収まる(tmp_path):
    photo = tmp_path / "tall.jpg"
    Image.new("RGB", (600, 1800), (10, 20, 30)).save(photo)

    got = compose_stage(photo, SCRIPT, source="e-Stat")
    assert got.size == SHORT_SIZE


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
