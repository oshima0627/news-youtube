"""BGM の関門を、動画を焼く全経路が通っていることのテスト。

CLAUDE.md の「関門は1つにして、全経路がそれを通る形にする」。同型の穴が
過去に3回開いている（known-issues 2・3・8番）ので、`audio_mix.mix()` を
足すだけでなく、**ffmpeg に渡る音声入力がミックス後のファイルであること**
を経路ごとに縛る。

ここでは ffmpeg の最終エンコードだけを差し替え、**音声のミックスは実物を
走らせる**。ミックスまでモックにすると「関門を呼んだつもり」で通ってしまう。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from scripts import audio_mix, build_long, build_short


def _tone(path: Path, freq: int, seconds: float) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={seconds}",
         "-filter:a", "volume=0.8", "-ar", "24000", "-ac", "1", str(path)],
        check=True, capture_output=True)
    return path


class _CapturedFfmpeg:
    """最終エンコードの ffmpeg を差し替えて、コマンドだけ受け取る。"""

    def __init__(self) -> None:
        self.cmd: list[str] = []
        # `build_short.subprocess` は subprocess モジュールそのものなので、
        # そこを差し替えると素通しのつもりの呼び出しも自分に戻ってくる。
        # 元の run を先に握っておく。
        self._real_run = subprocess.run

    def __call__(self, cmd, *a, **kw):
        # 映像を焼く1回だけを横取りする。音声の連結やミックスは実物を走らせる
        # （そこまでモックにすると「関門を呼んだつもり」で通ってしまう）。
        if "libx264" not in cmd:
            return self._real_run(cmd, *a, **kw)
        self.cmd = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def audio_input(self) -> Path:
        """コマンド中の `-i` のうち、concat リストでないほうを返す。"""
        inputs = [Path(self.cmd[i + 1])
                  for i, tok in enumerate(self.cmd) if tok == "-i"]
        return [p for p in inputs if p.suffix != ".txt"][-1]


@pytest.fixture
def bgm(tmp_path):
    return _tone(tmp_path / "bgm.wav", 800, 3)


# ---------------------------------------------------------------- ショート

def _short_workdir(tmp_path, monkeypatch):
    workdir = tmp_path / "work" / "abc123"
    workdir.mkdir(parents=True)
    _tone(workdir / "voice.wav", 300, 3)
    Image.new("RGB", (1600, 900), (80, 90, 110)).save(workdir / "photo.jpg")
    (workdir / "script.json").write_text(json.dumps({
        "headline": "照射は攻撃の一歩手前",
        "subtitle": "照射は攻撃の一歩手前",
        "quote_excerpt": "攻撃の一歩手前",
        "figure_label": "回数", "figure_value": "1回"}, ensure_ascii=False),
        encoding="utf-8")
    (workdir / "license.json").write_text(
        json.dumps({"attribution": "首相官邸"}, ensure_ascii=False),
        encoding="utf-8")

    recipes = tmp_path / "recipes"
    recipes.mkdir()
    (recipes / "abc123.json").write_text(json.dumps({
        "evidence": {"context": "国会会議録", "figure": "",
                     "quote": "レーダー照射は攻撃の一歩手前であります"}},
        ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(build_short, "ROOT", tmp_path)
    monkeypatch.setattr(build_short, "verify_duration",
                        lambda *a, **kw: 58.5)
    return workdir


def test_ショートはミックス後の音声をffmpegに渡す(tmp_path, monkeypatch, bgm):
    workdir = _short_workdir(tmp_path, monkeypatch)
    captured = _CapturedFfmpeg()
    monkeypatch.setattr(build_short.subprocess, "run", captured)
    monkeypatch.setattr(audio_mix, "BGM_PATH", bgm)

    build_short.build(workdir)

    audio = captured.audio_input()
    assert audio.name != "voice.wav"
    assert audio.exists()


def test_ショートのミックスにBGMが実際に混ざっている(tmp_path, monkeypatch, bgm):
    """渡されたファイルがナレーションのコピーで済まされていないこと。"""
    workdir = _short_workdir(tmp_path, monkeypatch)
    captured = _CapturedFfmpeg()
    monkeypatch.setattr(build_short.subprocess, "run", captured)
    monkeypatch.setattr(audio_mix, "BGM_PATH", bgm)

    build_short.build(workdir)

    mixed = audio_mix.measure(captured.audio_input())
    assert mixed.integrated == pytest.approx(audio_mix.TARGET_LUFS, abs=1.5)


def test_ショートの尺はナレーションのままでBGMに引きずられない(
        tmp_path, monkeypatch, bgm):
    """BGM は 3秒より長くても、出力尺はナレーションの実尺で確定させる。"""
    long_bgm = _tone(tmp_path / "long_bgm.wav", 800, 9)
    workdir = _short_workdir(tmp_path, monkeypatch)
    captured = _CapturedFfmpeg()
    monkeypatch.setattr(build_short.subprocess, "run", captured)
    monkeypatch.setattr(audio_mix, "BGM_PATH", long_bgm)

    build_short.build(workdir)

    at = captured.cmd.index("-t")
    assert float(captured.cmd[at + 1]) == pytest.approx(3.0, abs=0.05)


# ---------------------------------------------------------------- 長尺

def test_長尺もミックス後の音声をffmpegに渡す(tmp_path, monkeypatch, bgm):
    workdir = tmp_path / "work" / "long01"
    workdir.mkdir(parents=True)
    _tone(workdir / "p0.wav", 300, 3)
    (workdir / "long.json").write_text(json.dumps({"parts": [
        {"kind": "bumper", "wav": "p0.wav", "headline": "はじめに",
         "subtitle": "はじめに"}]}, ensure_ascii=False), encoding="utf-8")

    captured = _CapturedFfmpeg()
    monkeypatch.setattr(build_long.subprocess, "run", captured)
    monkeypatch.setattr(audio_mix, "BGM_PATH", bgm)
    monkeypatch.setattr(build_long, "compose_bumper",
                        lambda *a: Image.new("RGB", (192, 108), (0, 0, 0)))
    monkeypatch.setattr(build_long, "verify_duration", lambda *a, **kw: 3.0)

    build_long.build(workdir)

    audio = captured.audio_input()
    assert audio.name != "voice.wav"
    assert audio.exists()
    mixed = audio_mix.measure(audio)
    assert mixed.integrated == pytest.approx(audio_mix.TARGET_LUFS, abs=1.5)
