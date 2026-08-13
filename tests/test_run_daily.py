"""run_daily.py の判断ロジックの単体テスト。

外部（RSS収集・一次資料API・Anthropic API・VOICEVOX・ffmpeg・YouTube API）は
すべてモックし、以下の判断だけを検証する:

  - 枠が無い日は何も作らずに終わる
  - 枠より採用できた題材が少ないとき、無理に埋めずそのまま終わる
  - 投稿が成功した題材だけ seen.json に入る（失敗は次回また拾える）
  - --dry-run のときは seen.json を更新しない
  - 0本の日が続くと state/empty_streak.json が増え、3日で警告が出る
  - 1本の失敗（build/upload 等、題材固有の失敗）が当日全体を落とさない
  - 一次資料の取得元が全滅（EvidenceSourcesUnavailable）は環境不備として即座に中止する
  - 台本生成の環境不備（ScriptWriterUnavailable）は即座に中止する
  - 台本生成の題材固有の失敗（ScriptGenerationRejected）はその題材だけ飛ばす
  - 音声合成の失敗（環境不備の疑い）は即座に中止する
  - 画像（photo.jpg / license.json）が無い題材はその場で分かるメッセージで飛ばす
  - 予約枠を過ぎてから完成した題材は予約せず private のまま残し、既出には入れる
  - --schedule に渡す値が対象枠のISO8601文字列と一致する
  - 引用カードの文言が一次資料の逐語引用の部分文字列でなければ機械抽出に差し替える
  - 候補が0件／収集そのものが失敗した日は環境不備として非0終了する
  - upload成功後に --schedule が落ちても既出に入れる（翌日の重複投稿を防ぐ）
  - チャンネル取り違え（終了コード3）は環境不備として即座に中止する
  - レシピは画像が揃った題材についてのみ書き出す
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from scripts import run_daily
from scripts.evidence import Evidence, EvidenceSourcesUnavailable
from scripts.script_writer import Script, ScriptGenerationRejected, ScriptWriterUnavailable

JST = run_daily.JST

QUOTE = "これは十二文字以上ある逐語引用のダミーです。"

EVIDENCE = Evidence(
    kind="speech",
    source_url="https://kokkai.ndl.go.jp/#/detail?x=1",
    figure="",
    quote=QUOTE,
    context="第217回国会 衆議院予算委員会 2026-08-10 テスト太郎",
)

# 実行中の実時刻に依存しないよう、枠は固定日の時刻で表し、run_daily.datetime を
# 凍結して比較する。BEFORE_SLOTS はどちらの枠（07:30/18:30）よりも前。
# JST を明示する（run_daily は datetime.now(JST) で比較し slot.isoformat() を
# --schedule に渡すため、naive のままだとオフセットが落ちる）。
BEFORE_SLOTS = datetime(2026, 8, 11, 6, 5, tzinfo=JST)
SLOT_MORNING = datetime(2026, 8, 11, 7, 30, tzinfo=JST)
SLOT_EVENING = datetime(2026, 8, 11, 18, 30, tzinfo=JST)


def _evidence_for(keyword: str) -> Evidence:
    """題材ごとに出典URLの違う根拠。"""
    return replace(EVIDENCE, source_url=f"https://kokkai.ndl.go.jp/#/detail?q={keyword}")


def _script(title: str = "テストタイトル", quote_excerpt: str = "十二文字以上ある逐語引用") -> Script:
    return Script(
        title=title,
        headline="見出し",
        narration="ナレーション本文。" * 10,
        subtitle="字幕に出す要点",
        quote_excerpt=quote_excerpt,
        figure_label="件数",
        figure_value="1件",
        tags=["政治", "国会"],
    )


def _candidate(cid: str, title: str = "題材タイトル") -> dict:
    return {"id": cid, "title": title, "keyword": title, "category": "政治",
            "link": f"https://example.go.jp/{cid}"}


def _fake_ensure_photo(ev, dest: Path) -> dict:
    """run_daily.ensure_photo の差し替え。画像を1枚置いた体にする。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"fake-jpeg-bytes")
    return {"url": "https://upload.wikimedia.org/x.jpg",
            "attribution": "画像: テスト / CC BY 4.0（https://example.org/x）",
            "file": dest.name}


def _prepare_photo(workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "photo.jpg").write_bytes(b"fake-jpeg-bytes")
    (workdir / "license.json").write_text(
        json.dumps({"url": "https://example.go.jp/photo.jpg",
                   "attribution": "出典: テスト", "file": "photo.jpg"},
                  ensure_ascii=False),
        encoding="utf-8")


def _freeze_now(monkeypatch, instant: datetime) -> None:
    """run_daily.datetime.now() を固定する。

    slots はループ開始時に一度だけ計算され（テストでは pending_slots を
    モックするので影響しない）、アップロード直前の「枠がまだ未来か」の
    再確認は実行中に run_daily.datetime.now() を直接呼ぶ。実時刻に依存する
    と、実行環境の「今」次第でテストの当落が変わってしまうため凍結する。
    """
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant

    monkeypatch.setattr(run_daily, "datetime", _Frozen)


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

    def schedule_calls(self) -> list[list[str]]:
        return [c for c in self.upload_calls() if "--schedule" in c]


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
    monkeypatch.setattr(run_daily, "USED", state / "used.json")
    monkeypatch.setattr(run_daily, "STREAK", state / "empty_streak.json")
    return work, recipes, state


def _write_candidates(candidates: list[dict], work: Path) -> None:
    (work / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False), encoding="utf-8")


def _mock_success_path(monkeypatch, fail_for: set[str] | None = None) -> FakeRun:
    """collect/write/synthesize/build を正常系に固定し、FakeRun を返す。"""
    fake_run = FakeRun(fail_for=fail_for)
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    # 題材ごとに違う発言を返す。同じ発言を根拠にした動画を1日に2本作らない
    # よう run_daily が source_url で重複を落とすので、全題材に同じ Evidence を
    # 返すと2件目以降が「同じ発言を本日すでに使用」で飛ばされてしまう。
    monkeypatch.setattr(run_daily, "collect",
                        lambda keyword: [_evidence_for(keyword)])
    monkeypatch.setattr(run_daily, "write", lambda recipe: _script())
    # 画像取得は外部API（ja.wikipedia / Commons）を叩くので必ず差し替える。
    # 差し替え忘れると、テストが実ネットワークに出て遅くなるうえ、
    # 相手側の状態でテスト結果が変わる。
    monkeypatch.setattr(run_daily, "ensure_photo", _fake_ensure_photo)
    monkeypatch.setattr(run_daily, "synthesize", lambda text, dest: dest)
    monkeypatch.setattr(run_daily, "build", lambda workdir: workdir / "video.mp4")
    return fake_run


def test_枠が無い日は何も作らずに終了する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [])

    def _boom(cmd, **kwargs):
        raise AssertionError("枠が無いのに subprocess.run を呼んでいる")

    monkeypatch.setattr(run_daily.subprocess, "run", _boom)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "対象の枠は過ぎています" in out
    # 翌日分を作る手段があることを案内する（手で起動する運用のため）
    assert "--days-ahead" in out
    assert not (state / "seen.json").exists()
    assert not (state / "empty_streak.json").exists()


def test_枠より採用できた題材が少ないときは無理に埋めず終了する(tmp_path, monkeypatch, capsys):
    # 枠2つに対して候補は1件だけ採用できる状況を検証する（枠 > 採用数）。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "本日 1/2 本" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["only1"]           # 無理に2件目を作ろうとしていない


def test_複数候補があっても枠の数までしか作らない(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]  # 枠1つ
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cands = [_candidate("a"), _candidate("b")]
    _write_candidates(cands, work)
    for c in cands:
        _prepare_photo(work / c["id"])

    _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["a"]           # b には手を付けない


def test_limitで先頭の枠だけ埋める(tmp_path, monkeypatch, capsys):
    """--limit N は先頭からN枠だけ埋める。

    1枠ぶんだけ作り直したいことがある（公開前に内容を差し替えたいなど）。
    そのとき --days-ahead だけでは同じ日の**残り全部**を作ってしまい、
    すでに予約済みの枠に2本目が重なる。
    """
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cands = [_candidate("a"), _candidate("b")]
    _write_candidates(cands, work)
    for c in cands:
        _prepare_photo(work / c["id"])

    fake_run = _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--limit", "1"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "本日 1/1 本" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["a"]                       # b には手を付けない
    scheduled = fake_run.schedule_calls()
    assert len(scheduled) == 1
    # 埋めるのは先頭の枠。夕方の枠（予約済みのことがある）には触らない
    assert SLOT_MORNING.isoformat() in scheduled[0]


def test_limitが0以下なら受け付けない(tmp_path, monkeypatch):
    """0本作る指定は誤りとして弾く。

    そのまま通すと slots が空になり、「対象の枠は過ぎています」という
    実際とは違う理由が表示されて終わる。
    """
    _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--limit", "0"])

    with pytest.raises(SystemExit):
        run_daily.main()


def test_投稿が成功した題材だけseenに入る(tmp_path, monkeypatch):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    ok = _candidate("ok")
    bad = _candidate("bad")
    _write_candidates([ok, bad], work)
    _prepare_photo(work / ok["id"])
    _prepare_photo(work / bad["id"])

    # bad の workdir を含むアップロードコマンドだけ失敗させる
    fake_run = _mock_success_path(monkeypatch, fail_for={str(work / bad["id"])})
    monkeypatch.setattr("sys.argv", ["run_daily.py"])  # dry-run なし = 実アップロード経路

    run_daily.main()

    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]
    assert "bad" not in seen


def test_dry_run実行時はseenを更新しない(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    fake_run = _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "本日 1/1 本" in out          # 動画自体は作られる
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == []                    # だが seen には入らない
    # アップロードは一度も行われていない（dry-runなので）
    assert fake_run.upload_calls() == []


def test_scheduleには対象枠のISO8601文字列が渡される(tmp_path, monkeypatch):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    fake_run = _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    schedule_calls = fake_run.schedule_calls()
    assert len(schedule_calls) == 1
    cmd = schedule_calls[0]
    idx = cmd.index("--schedule")
    assert cmd[idx + 1] == "2026-08-11T07:30:00+09:00"


def test_枠を過ぎてから完成した題材は予約せずprivateのまま残しseenに入れる(
        tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    # アップロード直前の再確認時点で、対象枠(18:30)をわずかに過ぎている状況を再現する
    _freeze_now(monkeypatch, datetime(2026, 8, 11, 18, 31))

    cand = _candidate("late1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    fake_run = _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "予約せず" in out
    assert "要手動公開" in out
    # 予約(--schedule)は呼ばれていないが、通常アップロードは1回呼ばれている
    assert fake_run.schedule_calls() == []
    assert len(fake_run.upload_calls()) == 1
    # 動画は既にアップロード済みなので、重複投稿を避けるため既出に入れる
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["late1"]


def test_1本の失敗が当日全体を落とさない(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    bad = _candidate("bad")
    ok = _candidate("ok")
    _write_candidates([bad, ok], work)
    _prepare_photo(work / bad["id"])
    _prepare_photo(work / ok["id"])

    fake_run = _mock_success_path(monkeypatch)

    def fake_build(workdir: Path):
        if workdir.name == "bad":
            raise RuntimeError("ffmpegが失敗しました（テスト用）")
        return workdir / "video.mp4"

    monkeypatch.setattr(run_daily, "build", fake_build)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "失敗しました（この題材は飛ばします）: bad" in out
    assert "本日 1/2 本" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_一次資料の取得が連続3件失敗したら環境不備として中止する(tmp_path, monkeypatch, capsys):
    # 系統が国会会議録の1つしか無いため、1回の HTTP 失敗がそのまま
    # EvidenceSourcesUnavailable になる。1件目で中止すると 5xx が1回混ざった
    # だけでその日が0本になるので、連続 EVIDENCE_FAILURE_LIMIT 件で初めて中止する。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

    cands = [_candidate(f"c{i}", f"題材{i}") for i in range(5)]
    _write_candidates(cands, work)
    for c in cands:
        _prepare_photo(work / c["id"])

    collect_calls: list[str] = []

    def fake_collect(keyword):
        collect_calls.append(keyword)
        raise EvidenceSourcesUnavailable(
            f"一次資料の取得元が1系統も応答しませんでした（キーワード: {keyword}）: "
            "Connection refused")

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", fake_collect)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        run_daily.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "中止します" in err
    assert "接続できません" in err
    # 3件目で中止するので4件目以降には手を付けない
    assert collect_calls == ["題材0", "題材1", "題材2"]
    assert len(collect_calls) == run_daily.EVIDENCE_FAILURE_LIMIT
    assert fake_run.upload_calls() == []


def test_一次資料の取得が1回失敗しても次の候補へ進む(tmp_path, monkeypatch, capsys):
    # 一過性の 5xx が1回混ざっただけで日全体を落とさない（I2 の本題）。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    flaky = _candidate("flaky", "一時的に失敗")
    ok = _candidate("ok", "成功する題材")
    _write_candidates([flaky, ok], work)
    _prepare_photo(work / flaky["id"])
    _prepare_photo(work / ok["id"])

    def fake_collect(keyword):
        if keyword == "一時的に失敗":
            raise EvidenceSourcesUnavailable("503 Server Error（テスト用）")
        return [EVIDENCE]

    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "collect", fake_collect)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()          # SystemExit は起きない

    out = capsys.readouterr().out
    assert "連続 1/3 件目" in out
    assert "本日 1/1 本" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_全候補で一次資料の取得に失敗したら中止する(tmp_path, monkeypatch, capsys):
    # 候補が EVIDENCE_FAILURE_LIMIT 件に満たない日でも、一度も取得に成功して
    # いないなら「今日は題材が無かった」ではなく環境不備。静かな 0/1 本で
    # 終わらせない。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

    _write_candidates([_candidate("only1")], work)

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: (_ for _ in ()).throw(
        EvidenceSourcesUnavailable("Connection refused（テスト用）")))
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        run_daily.main()

    assert exc_info.value.code == 1
    assert "全候補" in capsys.readouterr().err


def test_台本生成が環境不備で失敗したら即座に中止する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

    cands = [_candidate("first"), _candidate("second")]
    _write_candidates(cands, work)
    for c in cands:
        _prepare_photo(work / c["id"])

    collect_calls: list[str] = []

    def fake_collect(keyword):
        collect_calls.append(keyword)
        return [EVIDENCE]

    def fake_write(recipe):
        raise ScriptWriterUnavailable(
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


def test_台本生成が題材固有の理由で拒否されたらその題材だけ飛ばして続行する(
        tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    rejected = _candidate("rejected")
    ok = _candidate("ok")
    _write_candidates([rejected, ok], work)
    _prepare_photo(work / rejected["id"])
    _prepare_photo(work / ok["id"])

    fake_run = _mock_success_path(monkeypatch)

    def fake_write(recipe):
        if recipe["id"] == "rejected":
            raise ScriptGenerationRejected("台本生成が拒否されました: 安全フィルタ（テスト用）")
        return _script()

    monkeypatch.setattr(run_daily, "write", fake_write)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    out = capsys.readouterr().out
    # SystemExit は起きず（中止ではなく）、この題材だけ飛ばして続行している
    assert "この題材は飛ばします" in out
    assert "rejected" in out
    assert "本日 1/2 本" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_音声合成が環境不備で失敗したら即座に中止する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    def fake_synthesize(text, dest):
        raise RuntimeError(
            "VOICEVOX のエンジンに接続できません: http://127.0.0.1:50021"
            "（テスト用）")

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    # 題材ごとに違う発言を返す。同じ発言を根拠にした動画を1日に2本作らない
    # よう run_daily が source_url で重複を落とすので、全題材に同じ Evidence を
    # 返すと2件目以降が「同じ発言を本日すでに使用」で飛ばされてしまう。
    monkeypatch.setattr(run_daily, "collect",
                        lambda keyword: [_evidence_for(keyword)])
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
    slots = [SLOT_MORNING, SLOT_EVENING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    # 題材ごとに違う見出しにする（_mock_success_path の collect は keyword
    # ごとに違う発言を返すので、同じ見出しだと2件目が重複除外で飛ばされる）
    ok = _candidate("ok", "題材ok")
    broken = _candidate("broken", "題材broken")
    _write_candidates([ok, broken], work)
    _prepare_photo(work / ok["id"])
    _prepare_photo(work / broken["id"])

    def fake_write(recipe):
        if recipe["id"] == "broken":
            raise ScriptWriterUnavailable("環境不備（テスト用）")
        return _script()

    fake_run = _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "write", fake_write)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    with pytest.raises(SystemExit):
        run_daily.main()

    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_画像を取得できない題材だけ飛ばす(tmp_path, monkeypatch, capsys):
    # 画像は発言者から自動で取る。取れないときだけ、その題材を飛ばす。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    no_photo = _candidate("no_photo", "画像が取れない題材")
    ok = _candidate("ok", "画像が取れる題材")
    _write_candidates([no_photo, ok], work)

    write_calls: list[str] = []

    def fake_write(recipe):
        write_calls.append(recipe["id"])
        return _script()

    def fake_ensure_photo(ev, dest):
        if "no_photo" in str(dest):
            raise RuntimeError("使える画像が見つかりませんでした")
        return _fake_ensure_photo(ev, dest)

    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "ensure_photo", fake_ensure_photo)
    monkeypatch.setattr(run_daily, "write", fake_write)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "画像を取得できません" in out
    assert "no_photo" in out
    # 画像が取れない題材では write() を呼んでいない（無駄なAPI課金をしない）
    assert write_calls == ["ok"]
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["ok"]


def test_手で用意した画像があれば自動取得で上書きしない(tmp_path, monkeypatch, capsys):
    # fetch_photo.py で差し替えた1枚を、次の実行が黙って上書きしてはいけない。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cand = _candidate("manual")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    def boom(ev, dest):
        raise AssertionError("手で用意した画像があるのに自動取得を呼んでいる")

    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "ensure_photo", boom)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    assert "本日 1/1 本" in capsys.readouterr().out


def test_採用できる題材が無ければ0本のまま終了する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

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
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

    # 候補は取れているが根拠が無かった日（＝正常系の0本）。候補0件は
    # 環境不備として非0終了するので、streak の対象にはならない。
    _write_candidates([_candidate("nofound")], work)

    fake_run = FakeRun()
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "3日続けて0本です" in out
    streak = json.loads((state / "empty_streak.json").read_text(encoding="utf-8"))
    assert streak["days"] == 3


# --- C1: 引用カードの文言が一次資料に由来することの保証 ------------------

def test_引用カードの文言が逐語引用の部分文字列ならそのまま使う():
    script = _script(quote_excerpt="十二文字以上ある逐語引用")
    got = run_daily.ensure_grounded_card(script, EVIDENCE.__dict__)
    assert got.quote_excerpt == "十二文字以上ある逐語引用"


def test_引用カードの文言が逐語引用に無ければ機械抽出に差し替える(capsys):
    # ここが破れると「モデルが作った文言に一次資料の出典キャプションが付く」。
    script = _script(quote_excerpt="一次資料には一切書かれていない捏造の一節")
    got = run_daily.ensure_grounded_card(script, EVIDENCE.__dict__)

    assert got.quote_excerpt != script.quote_excerpt
    assert got.quote_excerpt in QUOTE                    # 逐語引用に必ず含まれる
    assert got.quote_excerpt == QUOTE[:run_daily.QUOTE_EXCERPT_MAX_CHARS]
    out = capsys.readouterr().out
    assert "差し替え" in out or "機械的に抜き出します" in out


def test_引用カードの文言が空でも機械抽出に差し替える():
    # 空文字はどんな文字列の部分文字列でもあるので、素通しさせない
    got = run_daily.ensure_grounded_card(_script(quote_excerpt=""), EVIDENCE.__dict__)
    assert got.quote_excerpt == QUOTE[:run_daily.QUOTE_EXCERPT_MAX_CHARS]


def test_figureがある一次資料では引用の検証をせず数値カードのまま通す(capsys):
    # 数値カードの値は一次資料由来なので検証の対象外。ここで差し替えを
    # 走らせると、統計系統が戻ったときに数値カードが壊れる。
    ev = dict(EVIDENCE.__dict__, figure="関西空港便が30%減")
    script = _script(quote_excerpt="一次資料に無い文字列")
    got = run_daily.ensure_grounded_card(script, ev)

    assert got is script                                  # 何も差し替えていない
    assert capsys.readouterr().out == ""


def test_書き出すscript_jsonの引用が一次資料の部分文字列になっている(tmp_path, monkeypatch):
    # ensure_grounded_card が build() より前に効いていることを実際の経路で確認する。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    seen_at_build: dict = {}

    def fake_build(workdir: Path):
        seen_at_build.update(
            json.loads((workdir / "script.json").read_text(encoding="utf-8")))
        return workdir / "video.mp4"

    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "write",
                        lambda recipe: _script(quote_excerpt="捏造された数字と文言"))
    monkeypatch.setattr(run_daily, "build", fake_build)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    assert seen_at_build["quote_excerpt"] in QUOTE


# --- I1: 候補0件・収集失敗 -----------------------------------------------

def test_候補が0件なら環境不備として非0終了する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])
    _write_candidates([], work)

    monkeypatch.setattr(run_daily.subprocess, "run", FakeRun())
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        run_daily.main()

    assert exc_info.value.code == 1
    assert "候補が1件もありません" in capsys.readouterr().err
    # 「0本の日」ではなく環境不備なので streak には数えない
    assert not (state / "empty_streak.json").exists()


def test_collect_newsが非0終了したら日次実行を中止する(tmp_path, monkeypatch, capsys):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])

    monkeypatch.setattr(run_daily.subprocess, "run",
                        FakeRun(fail_for={"collect_news.py"}))
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        run_daily.main()

    assert exc_info.value.code == 1
    assert "候補の収集に失敗しました" in capsys.readouterr().err


# --- I3: upload成功後の失敗で重複投稿しない -------------------------------

def test_upload成功後にscheduleが落ちても既出に入れる(tmp_path, monkeypatch, capsys):
    # 既出に入れないと、翌日また同じ題材を作って**もう1本**アップロードする
    # （upload_youtube.py に重複防止が無い）。stuck_private と同じ扱い。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    # --schedule を含む2回目の呼び出しだけ失敗させる
    fake_run = _mock_success_path(monkeypatch, fail_for={"--schedule"})
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    assert len(fake_run.upload_calls()) == 2       # 1回目は成功、2回目で失敗
    out = capsys.readouterr().out
    assert "アップロード自体は成功" in out
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == ["only1"]


def test_uploadの1回目で落ちた題材は既出に入れない(tmp_path, monkeypatch):
    # こちらは YouTube 上に何も残っていないので、次回また拾えるようにする
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    _mock_success_path(monkeypatch, fail_for={str(work / cand["id"])})
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == []


# --- I4: チャンネル取り違え ------------------------------------------------

def test_チャンネル取り違えは環境不備として即座に中止する(tmp_path, monkeypatch, capsys):
    # token.json が別チャンネルだと全候補で同じ失敗を繰り返し、
    # 終了コード0の「本日 0/2 本」になってしまう。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING, SLOT_EVENING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cands = [_candidate("first"), _candidate("second")]
    _write_candidates(cands, work)
    for c in cands:
        _prepare_photo(work / c["id"])

    class _MismatchRun(FakeRun):
        def __call__(self, cmd, **kwargs):
            self.calls.append(list(cmd))
            if any("upload_youtube.py" in str(x) for x in cmd):
                raise subprocess.CalledProcessError(
                    run_daily.EXIT_CHANNEL_MISMATCH, cmd)
            return subprocess.CompletedProcess(cmd, 0)

    fake_run = _MismatchRun()
    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily.subprocess, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    with pytest.raises(SystemExit) as exc_info:
        run_daily.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "チャンネル" in err
    assert "中止します" in err
    # 1件目で中止するので2件目のアップロードは試みない
    assert len(fake_run.upload_calls()) == 1
    # 1回目のuploadも失敗しているので既出には入れない
    seen = json.loads((state / "seen.json").read_text(encoding="utf-8"))
    assert seen == []


# --- Minor: レシピの書き出し位置 -------------------------------------------

def test_画像が取れなかった題材のレシピは書き出さない(tmp_path, monkeypatch):
    # recipes/ は「再現の単位」であって「検討した候補の記録」ではない。
    # 一度も動画にならなかった題材のレシピが溜まり続けないようにする。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    no_photo = _candidate("no_photo", "画像が取れない題材")
    ok = _candidate("ok", "画像が取れる題材")
    _write_candidates([no_photo, ok], work)

    def fake_ensure_photo(ev, dest):
        if "no_photo" in str(dest):
            raise RuntimeError("使える画像が見つかりませんでした")
        return _fake_ensure_photo(ev, dest)

    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "ensure_photo", fake_ensure_photo)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    assert not (recipes / "no_photo.json").exists()
    assert (recipes / "ok.json").exists()


def test_1本でも作れたらstreakはリセットされる(tmp_path, monkeypatch):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    (state / "empty_streak.json").write_text(
        json.dumps({"days": 2}), encoding="utf-8")
    slots = [SLOT_MORNING]
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: slots)

    cand = _candidate("only1")
    _write_candidates([cand], work)
    _prepare_photo(work / cand["id"])

    _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    streak = json.loads((state / "empty_streak.json").read_text(encoding="utf-8"))
    assert streak["days"] == 0


# --- 同じ日に同じ発言を根拠にした動画を2本作らない -------------------------

def test_同じ発言を根拠にした動画は続けて作らない(tmp_path, monkeypatch, capsys):
    # RSSには同じ出来事の見出しが各社から並ぶ（「消費税減税 基本方針決定」と
    # 「食料品の消費税減税 5日にも閣議決定」など）。素通しにすると朝と夕方で
    # ほぼ同じ内容の動画が並び、まさに量産型と見なされる。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING, SLOT_EVENING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    first = _candidate("first", "消費税減税 基本方針決定")
    second = _candidate("second", "食料品の消費税減税 閣議決定へ")
    _write_candidates([first, second], work)
    _prepare_photo(work / first["id"])
    _prepare_photo(work / second["id"])

    fake_run = _mock_success_path(monkeypatch)
    # 見出しは違うが、行き着く一次資料（発言）は同じというケース
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "同じ発言を最近すでに使用" in out
    assert "本日 1/2 本" in out


def test_別の発言が取れるなら次点を使って2本目を作る(tmp_path, monkeypatch, capsys):
    # 重複除外は「その題材を捨てる」ではなく「別の根拠を探す」。collect() は
    # 関連性の高い順に返すので、使用済みを飛ばして次点を採る。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING, SLOT_EVENING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    first = _candidate("first", "消費税減税 基本方針決定")
    second = _candidate("second", "食料品の消費税減税 閣議決定へ")
    _write_candidates([first, second], work)
    _prepare_photo(work / first["id"])
    _prepare_photo(work / second["id"])

    other = replace(EVIDENCE, source_url="https://kokkai.ndl.go.jp/#/detail?x=2")
    fake_run = _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE, other])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    assert "本日 2/2 本" in capsys.readouterr().out
    sources = [json.loads((recipes / f"{c}.json").read_text(encoding="utf-8"))
               ["evidence"]["source_url"] for c in ("first", "second")]
    assert sources == [EVIDENCE.source_url, other.source_url]


def test_採れる題材が無い日は中止せず0本で終える(tmp_path, monkeypatch, capsys):
    # collect_news.py の EXIT_NO_TOPIC。天気やスポーツしか流れていない日は
    # 環境不備ではないので exit 1 にせず、0本の日として streak に数える。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots", lambda now, days_ahead=0: [SLOT_MORNING])

    def no_topic(cmd, **kwargs):
        raise subprocess.CalledProcessError(run_daily.EXIT_NO_TOPIC, cmd)

    monkeypatch.setattr(run_daily.subprocess, "run", no_topic)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()          # SystemExit を上げない

    assert "採れる題材がありませんでした" in capsys.readouterr().out
    assert json.loads((state / "empty_streak.json").read_text(
        encoding="utf-8"))["days"] == 1


def test_同じ出来事の見出しは続けて作らない(tmp_path, monkeypatch, capsys):
    # 発言URLの重複除外だけでは足りない。実測では「消費税減税 基本方針決定」
    # 「食料品消費税減税 政府が基本方針決定」「食料品の消費税減税 5日にも
    # 閣議決定」が同時に並び、それぞれ**別の**発言（片山・大島・玉木・中野）が
    # 取れてしまうため素通りした。朝と夕方で同じ出来事の動画が並ぶ。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING, SLOT_EVENING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    first = dict(_candidate("first", "消費税減税 基本方針決定"),
                 keyword="消費 減税 基本")
    second = dict(_candidate("second", "食料品の消費税減税 閣議決定へ"),
                  keyword="食料 消費 減税")
    _write_candidates([first, second], work)
    _prepare_photo(work / first["id"])
    _prepare_photo(work / second["id"])

    _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "同じ出来事を最近すでに使用" in out
    assert "本日 1/2 本" in out


def test_出来事が違えば2本作る(tmp_path, monkeypatch, capsys):
    # 重複除外が効きすぎて1日1本しか作れなくなっていないことの確認。
    # 実データから採った、検索語が1語だけ重なる別々の出来事
    # （永住許可の年収要件と、知事会の共生社会提言）。1語の一致で
    # 同じ出来事とみなすと、この日は片方しか作れなくなる。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING, SLOT_EVENING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    first = dict(_candidate("first", "外国人の永住許可 世帯年収を考慮"),
                 keyword="外国 永住 許可")
    second = dict(_candidate("second", "外国人との共生社会へ 全国知事会が提言"),
                  keyword="外国 共生 社会")
    _write_candidates([first, second], work)
    _prepare_photo(work / first["id"])
    _prepare_photo(work / second["id"])

    _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    assert "本日 2/2 本" in capsys.readouterr().out


# --- 日をまたいだ重複防止 ---------------------------------------------------

def test_昨日使った発言は今日もう一度使わない(tmp_path, monkeypatch, capsys):
    # これが無くて実際に事故った。初日に公開した「消費税減税」の題材が、
    # 翌日分でも**同じ発言（同じ出典URL）**を根拠にもう1本作られた。
    # seen.json は見出しのハッシュしか持たないので、同じ出来事が翌日に
    # 別の見出しで流れてくると素通りする。
    from datetime import date, timedelta as td

    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    yesterday = (date(2026, 8, 11)).isoformat()
    (state / "used.json").write_text(json.dumps([
        {"date": yesterday, "source_url": EVIDENCE.source_url,
         "keywords": ["消費", "減税", "基本"]}
    ], ensure_ascii=False), encoding="utf-8")

    cand = _candidate("today", "消費税減税の別の見出し")
    _write_candidates([cand], work)

    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    out = capsys.readouterr().out
    assert "同じ発言を最近すでに使用" in out
    assert "本日 0/1 本" in out


def test_使った発言を状態に書き出す(tmp_path, monkeypatch):
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    cand = dict(_candidate("a", "消費税減税の基本方針"), keyword="消費 減税 基本")
    _write_candidates([cand], work)

    _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py"])

    run_daily.main()

    entries = json.loads((state / "used.json").read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["source_url"].startswith("https://kokkai.ndl.go.jp/")
    assert set(entries[0]["keywords"]) == {"消費", "減税", "基本"}


def test_dry_runでは使った発言を記録しない(tmp_path, monkeypatch):
    # 動作確認のつもりの --dry-run で記録すると、本番実行のときにその題材が
    # 二度と拾われなくなる（seen.json を更新しないのと同じ理由）。
    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    _write_candidates([_candidate("a")], work)
    _mock_success_path(monkeypatch)
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    assert not (state / "used.json").exists()


def test_古い記録は重複判定から外れる(tmp_path, monkeypatch, capsys):
    # 同じ論点が数か月後にまた争点になることはある。永久に禁止はしない。
    from datetime import date, timedelta as td

    work, recipes, state = _setup_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(run_daily, "pending_slots",
                        lambda now, days_ahead=0: [SLOT_MORNING])
    _freeze_now(monkeypatch, BEFORE_SLOTS)

    old = (date(2026, 8, 11) - td(days=run_daily.USED_LOOKBACK_DAYS + 1)).isoformat()
    (state / "used.json").write_text(json.dumps([
        {"date": old, "source_url": EVIDENCE.source_url, "keywords": ["消費", "減税"]}
    ], ensure_ascii=False), encoding="utf-8")

    _write_candidates([_candidate("today")], work)
    _mock_success_path(monkeypatch)
    monkeypatch.setattr(run_daily, "collect", lambda keyword: [EVIDENCE])
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])

    run_daily.main()

    assert "本日 1/1 本" in capsys.readouterr().out
