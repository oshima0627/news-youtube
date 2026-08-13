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


def test_読み方の取得と合成でタイムアウトを使い分ける(monkeypatch, tmp_path):
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

    query = narrate.fetch_query("こんにちは", 13)
    narrate._synthesize_once(query, 13, 1.0, tmp_path / "voice.wav")

    timeouts = dict((url.rsplit("/", 1)[-1], t) for url, t in calls)
    assert timeouts["audio_query"] == narrate.TIMEOUT
    assert timeouts["synthesis"] == narrate.SYNTHESIS_TIMEOUT


def _query(moras: int, *, speed: float = 1.0, pause: float = 0.0,
           pre: float = 0.1, post: float = 0.1) -> dict:
    """モーラ1つ0.1秒（子音0.04＋母音0.06）の audio_query を組み立てる。"""
    return {
        "speedScale": speed,
        "prePhonemeLength": pre,
        "postPhonemeLength": post,
        "accent_phrases": [{
            "moras": [{"consonant_length": 0.04, "vowel_length": 0.06}
                      for _ in range(moras)],
            "pause_mora": ({"vowel_length": pause} if pause else None),
        }],
    }


def test_query_durationは合成せずに尺を返す():
    """audio_query が持つ長さの合計が実尺になる（実測誤差は最大0.17秒）。"""
    # 前後の無音0.1+0.1 + モーラ10個×0.1 + 句間の間0.3 = 1.5秒
    assert narrate.query_duration(_query(10, pause=0.3)) == pytest.approx(1.5)


def test_query_durationはspeedScaleで割る():
    assert narrate.query_duration(_query(10, pause=0.3, speed=1.5)) \
        == pytest.approx(1.0)


def test_fit_speedは尺を目標中央値に合わせる():
    # 目標中央値の2倍の長さなら、2倍速にすれば中央値になる
    long = _query(int((narrate.TARGET_MID * 2 - 0.2) / 0.1))
    assert narrate.query_duration(long) == pytest.approx(narrate.TARGET_MID * 2)
    # 可動域に収まる範囲で（2.0 は SPEED_MAX を超えるのでクランプされる）
    assert narrate.fit_speed(long) == narrate.SPEED_MAX


def test_fit_speedは可動域に収める():
    assert narrate.fit_speed(_query(1)) == narrate.SPEED_MIN
    assert narrate.fit_speed(_query(5000)) == narrate.SPEED_MAX


def test_合成は1回で済ませる(monkeypatch, tmp_path):
    """読み方から尺を計算するので、再合成に入らない。

    もとは speedScale=1.0 で決め打ちして実尺を測り、外れていたら
    合成し直していた。本番尺の合成は1回2分近くかかるので、これが
    そのまま実行時間の倍増になる。字数からの推定に変えても解決せず
    （2本中1本が55.41秒で下振れ）、audio_query から計算する形にした。
    """
    speeds = []
    query = _query(500)                      # 50.2秒ぶんの読み方

    def _fake_once(q, sid, speed, dest):
        speeds.append(speed)
        return narrate.query_duration(q) / speed   # 計算どおりに鳴ったとする

    monkeypatch.setattr(narrate, "ensure_engine", lambda: None)
    monkeypatch.setattr(narrate, "_speaker_id", lambda: 13)
    monkeypatch.setattr(narrate, "fetch_query", lambda text, sid: query)
    monkeypatch.setattr(narrate, "_synthesize_once", _fake_once)
    monkeypatch.setattr(narrate, "_write_segments", lambda *a: None)

    narrate.synthesize("本文", tmp_path / "voice.wav")

    assert len(speeds) == 1, "1回で収まるはずが再合成している"
    assert speeds[0] == pytest.approx(
        narrate.query_duration(query) / narrate.TARGET_MID)


def test_計算が外れたら従来どおり再合成する(monkeypatch, tmp_path):
    """安全網は残す（エンジンの仕様が変わって計算が合わなくなったとき）。"""
    speeds = []

    def _fake_once(q, sid, speed, dest):
        speeds.append(speed)
        # 計算の2倍の長さで鳴ってしまう状況
        return narrate.query_duration(q) / speed * 2 if len(speeds) == 1 \
            else narrate.TARGET_MID

    monkeypatch.setattr(narrate, "ensure_engine", lambda: None)
    monkeypatch.setattr(narrate, "_speaker_id", lambda: 13)
    monkeypatch.setattr(narrate, "fetch_query", lambda text, sid: _query(500))
    monkeypatch.setattr(narrate, "_synthesize_once", _fake_once)
    monkeypatch.setattr(narrate, "_write_segments", lambda *a: None)

    narrate.synthesize("本文", tmp_path / "voice.wav")

    assert len(speeds) == 2


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
