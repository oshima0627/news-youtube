"""run_daily.py の判断ロジックの単体テスト。

外部（RSS収集・一次資料API・Anthropic API・VOICEVOX・ffmpeg・YouTube API）は
すべてモックし、以下の判断だけを検証する:

  - 枠が無い日は何も作らずに終わる
  - 枠より採用できた題材が少ないとき、無理に埋めずそのまま終わる
  - 投稿が成功した題材だけ seen.json に入る（失敗は次回また拾える）
  - 0本の日が続くと state/empty_streak.json が増え、3日で警告が出る
  - 1本の失敗（build/upload 等、題材固有の失敗）が当日全体を落とさない
  - 台本生成・音声合成の失敗（環境不備の疑い）は題材を飛ばさず即座に中止する
  - 画像（photo.jpg / license.json）が無い題材はその場で分かるメッセージで飛ばす
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from scripts import run_daily
from scripts.evidence import Evidence
from scripts.script_writer import Script

EVIDENCE = Evidence(
    kind="speech",
    source_url="https://kokkai.ndl.go.jp/#/detail?x=1",
    figure="",
    quote="これは十二文字以上ある逐語引用のダミーです。",
    context="第217回国会 衆議院予算委員会 2026-08-10 テスト太郎",
)


def _script(title: str = "テストタイトル") -> Script:
    return Script(
        title=title,
        headline="見出し",
        narration="ナレーション本文。" * 10,
        figure_label="件数",
        figure_value="1件",
        tags=["政治", "国会"],
    )


def _candidate(cid: str, title: str = "題材タイトル") -> dict:
    return {"id": cid, "title": title, "keyword": title, "category": "政治",
            "link": f"https://example.go.jp/{cid}"}


def _prepare_photo(workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "photo.jpg").write_bytes(b"fake-jpeg-bytes")
    (workdir / "license.json").write_text(
        json.dumps({"url": "https://example.go.jp/photo.jpg",
                   "attribution": "出典: テスト", "file": "photo.jpg"},
                  ensure_ascii=False),
        encoding="utf-8")


class FakeRun:
    """scripts.run_daily.subprocess.run の差し替え。

    collect_news.py の呼び出しは無視する（候補は各テストが直接
    run_daily.CANDIDATES に書いておく）。upload_youtube.py の呼び出しは
    fail_for に含まれる文字列（通常は workdir のパス文字列）を含むコマンド
    に対して CalledProcessError を上げる。
    """

    def __init__(self, fail_for: set[str] | None = None):
        self.calls: list[list[str]] = []
        self.fail_for = fail_for or set()

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        joined = " ".join(str(c) for c in cmd)
        for needle in self.fail_for:
            if needle in joined:
                raise subprocess.CalledProcessError(1, cmd, stderr="fake failure")
        return subprocess.CompletedProcess(cmd, 0)

    def upload_calls(self) -> list[list[str]]:
        return [c for c in self.calls if any("upload_youtube.py" in str(x) for x in c)]


def _setup_paths(tmp_path, monkeypatch):
    work = tmp_path / "work"
    recipes = tmp_path / "recipes"
    state = tmp_path / "state"
    work.mkdir()
    recipes.mkdir()
    state.mkdir()
    monkeypatch.setattr(run_daily, "WORK", work)
    monkeypatch.setattr(run_daily, "RECIPES", recipes)
    monkeypatch.setattr(run_daily, "CANDIDATES", work / "candidates.json")
    monkeypatch.setattr(run_daily, "SEEN", state / "seen.json")
    monkeypatch.setattr(run_daily, "STREAK", state / "empty_streak.json")
    return work, recipes, state


def _write_candidates(candidates: list[dict], work: Path) -> None:
    (work / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False), encoding="utf-8")


def test_枠が無い日は何も作らずに終了する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: [])

    def _boom(cmd, **kwargs):
        raise AssertionError("枠が無いのに subprocess.run を呼んでいる")

    monkeypatch.setattr(run_daily.subprocess, "run", _boom)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    assert "本日の枠は過ぎています" in capsys.readouterr().out
    assert not (state / "seen.json").exists()
    assert not (state / "empty_streak.json").exists()


def test_枠より採用できた題材が少ないときは無理に埋めず終了する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30)]  # 枠1つ
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", lambda recipe: _script())
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)
    monkeypatch.setattr(run_daily, "build", lambda workdir: workdir / "video.mp4")
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "本日 1/1 本" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["only1"]


def test_複数候補があっても枠の数までしか作らない(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30)]  # 枠1つ
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    cands = [_candidate("a"), _candidate("b")]
    _write_candidates(cands, work)
    for c in cands:
        _prepare_photo(work / c["id"])

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", lambda recipe: _script())
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)
    monkeypatch.setattr(run_daily, "build", lambda workdir: workdir / "video.mp4")
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["a"]           # b には手を付けない


def test_投稿が成功した題材だけseenに入る(tmp_path, monkeypatch):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30), datetime(2026, 8, 11, 18, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    ok = _candidate("ok")
    bad = _candidate("bad")
    _write_candidates([ok, bad], work)
    _prepare_photo(work / ok["id"])
    _prepare_photo(work / bad["id"])

    # bad の workdir を含むアップロードコマンドだけ失敗させる
    fake_run = FakeRun(fail_for={str(work / bad["id"])})
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", lambda recipe: _script())
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)
    monkeypatch.setattr(run_daily, "build", lambda workdir: workdir / "video.mp4")
    monkeypatch.setattr("sys.argv", ["run_daily.py"])  # dry-run なし = 実アップロード経路

    run_daily.main()

    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]
    assert "bad" not in seen


def test_1本の失敗が当日全体を落とさない(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30), datetime(2026, 8, 11, 18, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    bad = _candidate("bad")
    ok = _candidate("ok")
    _write_candidates([bad, ok], work)
    _prepare_photo(work / bad["id"])
    _prepare_photo(work / ok["id"])

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", lambda recipe: _script())
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)

    def fake_build(workdir: Path):
        if workdir.name == "bad":
            raise RuntimeError("ffmpegが失敗しました（テスト用）")
        return workdir / "video.mp4"

    monkeypatch.setattr(run_daily, "build", fake_build)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "失敗しました（この題材は飛ばします）: bad" in out
    assert "本日 1/2 本" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_台本生成が環境不備で失敗したら即座に中止する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30), datetime(2026, 8, 11, 18, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    cands = [_candidate("first"), _candidate("second")]
    _write_candidates(cands, work)
    for c in cands:
        _prepare_photo(work / c["id"])

    collect_calls: list[str] = []

    def fake_collect(keyword):
        collect_calls.append(keyword)
        return [EVIDENCE]

    def fake_write(recipe):
        raise RuntimeError(
            "Anthropic API の認証情報を解決できませんでした。"
            "ANTHROPIC_API_KEY を設定するか、`ant auth login` でプロファイルを"
            "作成してください。（元のエラー: dummy）")

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", fake_collect)
    monkeypatch.setattr(run_daily, "write", fake_write)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        run_daily.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "中止します" in err
    assert "ANTHROPIC_API_KEY" in err
    # 1件目で中止するので2件目には手を付けない
    assert collect_calls == ["題材タイトル"]
    # アップロードは一度も行われていない
    assert fake_run.upload_calls() == []


def test_音声合成が環境不備で失敗したら即座に中止する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    def fake_synthesize(text, dest):
        raise RuntimeError(
            "VOICEVOX のエンジンに接続できません: http://127.0.0.1:50021"
            "（テスト用）")

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", lambda recipe: _script())
    monkeypatch.setattr(run_daily, "synthesize", fake_synthesize)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        run_daily.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "中止します" in err
    assert "VOICEVOX" in err


def test_環境不備で中止してもそこまでの成功分はseenに残る(tmp_path, monkeypatch):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30), datetime(2026, 8, 11, 18, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    ok = _candidate("ok")
    broken = _candidate("broken")
    _write_candidates([ok, broken], work)
    _prepare_photo(work / ok["id"])
    _prepare_photo(work / broken["id"])

    def fake_write(recipe):
        if recipe["id"] == "broken":
            raise RuntimeError("環境不備（テスト用）")
        return _script()

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", fake_write)
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)
    monkeypatch.setattr(run_daily, "build", lambda workdir: workdir / "video.mp4")
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    with pytest.raises(SystemExit):
        run_daily.main()

    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_画像未準備の題材はその場で分かるメッセージで飛ばす(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    no_photo = _candidate("no_photo")
    ok = _candidate("ok")
    _write_candidates([no_photo, ok], work)
    # no_photo には画像を用意しない
    _prepare_photo(work / ok["id"])

    write_calls: list[str] = []

    def fake_write(recipe):
        write_calls.append(recipe["id"])
        return _script()

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", fake_write)
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)
    monkeypatch.setattr(run_daily, "build", lambda workdir: workdir / "video.mp4")
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "画像未準備" in out
    assert "no_photo" in out
    assert "fetch_photo.py" in out
    # 画像が無い題材では write() を呼んでいない（無駄なAPI課金をしない）
    assert write_calls == ["ok"]
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_採用できる題材が無ければ0本のまま終了する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [datetime(2026, 8, 11, 7, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    _write_candidates([_candidate("nofound")], work)

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "本日 0/1 本" in out
    streak = json.loads((state / "empty_streak.json").read_text(encoding="utf-8"))
    assert streak["days"] == 1


def test_0本が3日続くと警告が出る(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    (state / "empty_streak.json").write_text(
        json.dumps({"days": 2}), encoding="utf-8")
    slots = [datetime(2026, 8, 11, 7, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    _write_candidates([], work)

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "3日続けて0本です" in out
    streak = json.loads((state / "empty_streak.json").read_text(encoding="utf-8"))
    assert streak["days"] == 3


def test_1本でも作れたらstreakはリセットされる(tmp_path, monkeypatch):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    (state / "empty_streak.json").write_text(
        json.dumps({"days": 2}), encoding="utf-8")
    slots = [datetime(2026, 8, 11, 7, 30)]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now: slots)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr(run_daily, "write", lambda recipe: _script())
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)
    monkeypatch.setattr(run_daily, "build", lambda workdir: workdir / "video.mp4")
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    streak = json.loads((state / "empty_streak.json").read_text(encoding="utf-8"))
    assert streak["days"] == 0
