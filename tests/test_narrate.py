import wave
from pathlib import Path

import pytest

from scripts import narrate
from scripts.narrate import resolve_speaker, wav_duration_seconds

SPEAKERS = [
    {"name": "四国めたん", "styles": [{"name": "ノーマル", "id": 2}]},
    {"name": "青山龍星", "styles": [
        {"name": "ノーマル", "id": 13},
        {"name": "熱血", "id": 81},
    ]},
]


def test_名前からノーマルの話者IDを引く():
    assert resolve_speaker(SPEAKERS, "青山龍星") == 13


def test_居ない話者は例外にする():
    # 黙って別の声で作ると、既存視聴者の耳と合わない動画が公開される
    with pytest.raises(ValueError, match="見つかりません"):
        resolve_speaker(SPEAKERS, "存在しない話者")


def _write_silence_wav(path: Path, seconds: float, framerate: int = 24000) -> None:
    """wave 標準ライブラリだけで無音の wav を作る（テスト用フィクスチャ）。"""
    nframes = int(seconds * framerate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * nframes)


def test_wav_duration_secondsはフレーム数とレートから秒数を返す(tmp_path):
    wav_path = tmp_path / "sample.wav"
    _write_silence_wav(wav_path, seconds=2.5, framerate=24000)

    assert wav_duration_seconds(wav_path) == pytest.approx(2.5, abs=0.01)


def test_ensure_engine_候補パスが無ければ例外にする(monkeypatch, tmp_path):
    # 無音動画を無自覚に投稿しないための最後の砦。ここで黙って通ってはいけない。
    def _fail_get(*_a, **_k):
        raise ConnectionError("no engine")

    missing = tmp_path / "nowhere" / "run.exe"
    monkeypatch.setattr(narrate.requests, "get", _fail_get)
    monkeypatch.setattr(narrate, "ENGINE_EXE_CANDIDATES", (missing,))

    with pytest.raises(RuntimeError) as exc:
        narrate.ensure_engine()
    assert str(missing) in str(exc.value)


def test_ensure_engine_起動しても応答しなければ例外にする(monkeypatch, tmp_path):
    exe = tmp_path / "run.exe"
    exe.write_bytes(b"")  # exists() が真になればよく、実行はしない

    def _fail_get(*_a, **_k):
        raise ConnectionError("no engine")

    popen_calls = []

    def _fake_popen(args, **_kwargs):
        popen_calls.append(args)

        class _Proc:
            pass
        return _Proc()

    monkeypatch.setattr(narrate.requests, "get", _fail_get)
    monkeypatch.setattr(narrate, "ENGINE_EXE_CANDIDATES", (exe,))
    monkeypatch.setattr(narrate.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(narrate.time, "sleep", lambda *_a: None)  # 待たずにテスト

    with pytest.raises(RuntimeError):
        narrate.ensure_engine()

    assert popen_calls, "起動を試みていない"


def test_合成のタイムアウトは本番尺の音声を作りきれる長さにする():
    """/synthesis のタイムアウトは、最長の尺を合成する実測時間より十分長いこと。

    CPU版エンジンの実測で、63.5秒の音声の合成に **115.9秒** かかった
    （＝音声1秒あたり約1.8秒）。メタデータ用の TIMEOUT（120秒）を
    /synthesis にも使っていたため余裕が4秒しかなく、他プロセスの負荷で
    容易に超える。超えると synthesize() が例外を投げ、run_daily.py は
    それを「VOICEVOX未起動」＝環境不備と見なして**日次実行ごと中止**する
    （実際に2回連続で0本になった）。実測の約2倍では足りないので、
    最長尺 TARGET_MAX に対して4倍の秒数を最低ラインとする。
    """
    assert narrate.SYNTHESIS_TIMEOUT >= narrate.TARGET_MAX * 4


def test_合成は長い方のタイムアウトで呼ぶ(monkeypatch, tmp_path):
    """audio_query は短い TIMEOUT、/synthesis は SYNTHESIS_TIMEOUT で呼ぶ。

    定数を足しただけで使い忘れると実測どおり120秒で切れるので、
    実際に渡している値をここで押さえる。
    """
    wav_path = tmp_path / "src.wav"
    _write_silence_wav(wav_path, seconds=1.0)
    wav_bytes = wav_path.read_bytes()

    calls = []

    class _Response:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _fake_post(url, **kwargs):
        calls.append((url, kwargs.get("timeout")))
        if url.endswith("/audio_query"):
            return _Response(payload={"accent_phrases": []})
        return _Response(content=wav_bytes)

    monkeypatch.setattr(narrate.requests, "post", _fake_post)

    narrate._synthesize_once("こんにちは", 13, 1.0, tmp_path / "voice.wav")

    timeouts = dict((url.rsplit("/", 1)[-1], t) for url, t in calls)
    assert timeouts["audio_query"] == narrate.TIMEOUT
    assert timeouts["synthesis"] == narrate.SYNTHESIS_TIMEOUT


def test_ensure_engine_応答済みなら何もせず即returnする(monkeypatch):
    class _OKResponse:
        def raise_for_status(self):
            return None

    calls = {"get": 0}

    def _ok_get(*_a, **_k):
        calls["get"] += 1
        return _OKResponse()

    def _fake_popen(*_a, **_k):
        raise AssertionError("応答済みなのに起動を試みてはいけない")

    monkeypatch.setattr(narrate.requests, "get", _ok_get)
    monkeypatch.setattr(narrate.subprocess, "Popen", _fake_popen)

    narrate.ensure_engine()

    assert calls["get"] == 1
