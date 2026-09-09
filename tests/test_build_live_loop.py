import json
import subprocess
import wave
from pathlib import Path

import pytest

from scripts.build_live_loop import narration_text, render_frame, select_recipes, speech_window
from scripts.cards_wide import WIDE_SIZE
from scripts.narrate import SECONDS_PER_CHAR

_R = {
    "id": "aaa", "headline": "奨学金の返済が長期化している", "category": "教育",
    "evidence": {"quote": "平均で十五年かけて返済しています。",
                 "context": "第221回国会 衆議院特別委員会 2026-05-08 谷浩一郎",
                 "source_url": "https://kokkai.ndl.go.jp/txt/1/1", "speaker": "谷浩一郎"},
}


def _recipe(tmp_path: Path, rid: str, category: str) -> None:
    (tmp_path / f"{rid}.json").write_text(json.dumps({
        "id": rid, "headline": f"{rid}の見出し", "keyword": "税",
        "category": category,
        "evidence": {"kind": "speech", "source_url": "https://kokkai.ndl.go.jp/txt/1/1",
                     "figure": "", "quote": "逐語の引用文です。", "context": "第221回国会 2026-05-08 谷浩一郎",
                     "speaker": "谷浩一郎"},
    }, ensure_ascii=False), encoding="utf-8")


def test_レシピをid順に読み込む(tmp_path):
    _recipe(tmp_path, "bbb", "税")
    _recipe(tmp_path, "aaa", "税")
    got = select_recipes(tmp_path)
    assert [r["id"] for r in got] == ["aaa", "bbb"]


def test_除外したカテゴリのレシピは入らない(tmp_path):
    _recipe(tmp_path, "aaa", "税")
    _recipe(tmp_path, "bbb", "選挙")
    got = select_recipes(tmp_path, exclude_categories=frozenset({"選挙"}))
    assert [r["id"] for r in got] == ["aaa"]


def test_除外しなければ選挙も入る(tmp_path):
    _recipe(tmp_path, "bbb", "選挙")
    assert len(select_recipes(tmp_path)) == 1


def test_見出しと引用と出典がこの順で入る():
    got = narration_text(_R)
    assert got.index("奨学金") < got.index("十五年") < got.index("谷浩一郎")


def test_引用は逐語のまま入る():
    assert _R["evidence"]["quote"] in narration_text(_R)


def test_引用に無い言葉を足さない():
    """台本は見出し・引用・出典の連結だけ。ここに定型の地の文を入れると、
    一次資料に無い文字列が出典付きで読み上げられることになる。"""
    got = narration_text(_R)
    for part in (_R["headline"], _R["evidence"]["quote"], _R["evidence"]["context"]):
        got = got.replace(part, "", 1)
    # 残ってよいのは区切りの句読点と空白だけ
    assert set(got) <= set("。、 \n"), f"余計な地の文が入っている: {got!r}"


def test_フレームは1920x1080():
    assert render_frame(_R).size == WIDE_SIZE


def test_引用カードに載せる文字列は一次資料の逐語(monkeypatch):
    """描画に渡した文字列が evidence.ground_excerpt を通っていること。
    通っていなければ、モデル生成値に出典が付く経路がここに開く。"""
    seen = []
    import scripts.build_live_loop as m
    original = m.ground_excerpt
    monkeypatch.setattr(m, "ground_excerpt",
                        lambda excerpt, quote: seen.append((excerpt, quote)) or original(excerpt, quote))
    render_frame(_R)
    assert seen == [(_R["evidence"]["quote"], _R["evidence"]["quote"])]


def test_尺の窓は文字数から決まる():
    text = "あ" * 200
    lo, hi = speech_window(text)
    est = 200 * SECONDS_PER_CHAR
    assert lo < est < hi


def test_短い題材でも窓が反転しない():
    lo, hi = speech_window("あ")
    assert 0 < lo < hi


# ---------------------------------------------------------------- build()
#
# VOICEVOX と ffmpeg はどちらも重い（前者はエンジン起動・後者は実プロセス）ので、
# build() のテストでは synthesize / mix / subprocess.run だけを置き換える。
# render_frame は実物を使う（PIL の描画だけで、外部プロセスは呼ばない）。
# 置き換えた合成・mix も wave モジュールで実物の wav を書くので、
# wav_duration_seconds が読む実尺は本物のまま検証できる。

def _silence_wav(path: Path, seconds: float) -> Path:
    """外部プロセスを使わずに実尺だけ正しい wav を作る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    n_frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path


def test_buildはレシピが空だと分かるメッセージで止まる(tmp_path):
    """空リストのまま進めると frames[-1] が素の IndexError になり、
    「レシピが0件だった」という本当の原因が読み取れない。"""
    from scripts.build_live_loop import build
    with pytest.raises(ValueError, match="recipes"):
        build(tmp_path / "loop.mp4", [])


def test_buildはレシピごとに合成とmixを呼びffmpegの結合コマンドを組む(tmp_path, monkeypatch):
    import scripts.build_live_loop as m

    mix_calls = []

    def fake_synthesize(text, dest, *, target_min, target_max):
        assert target_min < target_max          # 呼び出し側が窓を渡していること
        _silence_wav(dest, 2.0)
        return dest

    def fake_mix(voice_path, out_path, *, bgm_path=None):
        mix_calls.append(Path(voice_path))
        _silence_wav(out_path, 3.0)              # mix後の実尺（BGM敷き後）

    run_calls = []

    def fake_run(cmd, **kwargs):
        run_calls.append(cmd)

    monkeypatch.setattr(m, "synthesize", fake_synthesize)
    monkeypatch.setattr(m, "mix", fake_mix)
    monkeypatch.setattr(m.subprocess, "run", fake_run)

    recipe_b = dict(_R, id="bbb")
    out_path = tmp_path / "out" / "loop.mp4"
    out = m.build(out_path, [_R, recipe_b])

    assert out == out_path

    # BGM の関門（mix）はレシピと1対1で、全経路が必ず通る
    assert [p.name for p in mix_calls] == ["000_voice.wav", "001_voice.wav"]

    # ffmpeg は concat 2本を入力に、配信側が -c copy できる形で焼く
    assert len(run_calls) == 1
    cmd = run_calls[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-g") + 1] == "60"
    assert cmd[cmd.index("-keyint_min") + 1] == "60"

    work = out_path.parent / "parts"
    audio_lines = (work / "audio.txt").read_text(encoding="utf-8").splitlines()
    assert len(audio_lines) == 2   # レシピ2件ぶんの mix 済み wav

    frame_lines = (work / "frames.txt").read_text(encoding="utf-8").splitlines()
    last_png = (work / "001.png").as_posix()
    assert frame_lines.count(f"file '{last_png}'") == 2   # concat は最後を2度書く
    assert "duration 3.000" in frame_lines   # mix後の実尺（fake_mixが書いた3秒）がそのまま使われる


def test_buildはffmpeg失敗時に原因つきの例外にする(tmp_path, monkeypatch):
    """check=True だけに任せると失敗原因（stderr）が読み取れない。"""
    import scripts.build_live_loop as m

    def fake_synthesize(text, dest, *, target_min, target_max):
        _silence_wav(dest, 1.0)
        return dest

    def fake_mix(voice_path, out_path, *, bgm_path=None):
        _silence_wav(out_path, 1.0)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="ffmpeg boom")

    monkeypatch.setattr(m, "synthesize", fake_synthesize)
    monkeypatch.setattr(m, "mix", fake_mix)
    monkeypatch.setattr(m.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg boom"):
        m.build(tmp_path / "loop.mp4", [_R])
