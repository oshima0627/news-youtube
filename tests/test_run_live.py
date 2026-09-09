"""24時間ライブ配信の関門のテスト。

守りたいのは2つ: **12時間を超えたら例外で止まる**（アーカイブが作られず
再生時間が丸ごと0になる）ことと、**二重起動ロックが枠を作る関数の中に
あって呼び出し側からは外せない**こと。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.run_live import (FFMPEG_RESTART_LIMIT, FFMPEG_RESTART_WINDOW,
                              HARD_LIMIT, ROTATE_AFTER, ROTATION_GIVE_UP_AFTER,
                              ArchiveWindowExceeded,
                              StreamNotActive, assert_within_archive_window,
                              record_restart, should_give_up_rotation,
                              should_rotate,
                              too_many_restarts, wait_for_stream_active)

T0 = datetime(2026, 9, 9, 0, 0, 0)


def test_11時間半で切り替える():
    assert not should_rotate(T0, T0 + timedelta(hours=11, minutes=29))
    assert should_rotate(T0, T0 + timedelta(hours=11, minutes=31))


def test_切り替えの閾値は12時間より手前():
    """12時間を超えるとアーカイブが作られず、その配信の再生時間は
    1分も4,000時間に入らない。マージンが無いと一度の遅延で全部失う。"""
    assert ROTATE_AFTER < HARD_LIMIT
    assert HARD_LIMIT <= timedelta(hours=12)
    assert HARD_LIMIT - ROTATE_AFTER >= timedelta(minutes=20)


def test_12時間に達したら例外で止まる():
    assert_within_archive_window(T0, T0 + timedelta(hours=11, minutes=59))
    with pytest.raises(ArchiveWindowExceeded):
        assert_within_archive_window(T0, T0 + timedelta(hours=12))


# ------------------------------------- 切り替えのやり直しには終わりがある

def test_マージンの内側なら切り替えをやり直す():
    """API の一時的な失敗で11時間半ぶんを捨てない。30分のマージンは
    このやり直しのためにある。"""
    assert not should_give_up_rotation(T0, T0 + timedelta(hours=11, minutes=31))
    assert not should_give_up_rotation(T0, T0 + timedelta(hours=11, minutes=54))


def test_12時間の手前でやり直しを諦める():
    """やり直しに終わりが無いと、止まるころには12時間を跨いだあとで
    アーカイブが1本も作られない。「30分ぶんのやり直しを失う」が
    「11時間半のアーカイブを失う」に化ける。"""
    assert should_give_up_rotation(T0, T0 + timedelta(hours=11, minutes=55))
    assert should_give_up_rotation(T0, T0 + timedelta(hours=12))


def test_諦める線はローテーションと12時間の間にある():
    assert ROTATE_AFTER < ROTATION_GIVE_UP_AFTER < HARD_LIMIT
    assert HARD_LIMIT - ROTATION_GIVE_UP_AFTER >= timedelta(minutes=5)


def test_諦めた時点ではまだアーカイブの窓の中にいる():
    """諦めた直後に finally が complete_broadcast する。その瞬間に
    12時間を越えていたら、やり直しを打ち切った意味が無い。"""
    assert_within_archive_window(T0, T0 + ROTATION_GIVE_UP_AFTER)
    # 諦めるより前に、切り替えを試す機会が何ティックもあること
    assert ROTATION_GIVE_UP_AFTER - ROTATE_AFTER >= timedelta(minutes=10)


# ---------------------------------------------------------------- 枠の管理

class _FakeStreams:
    """liveStreams.list の最小の身代わり。呼ぶたびに次の状態を返す。"""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def list(self, **kw):
        return self

    def execute(self):
        self.calls += 1
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"items": [{"status": {"streamStatus": status}}]}


class _FakeYouTube:
    """liveBroadcasts.insert / bind / transition の最小の身代わり。"""

    def __init__(self, stream_statuses=("active",)):
        self.calls = []
        self.streams = _FakeStreams(stream_statuses)

    def liveStreams(self):
        return self.streams

    def liveBroadcasts(self):
        return self

    def insert(self, **kw):
        self.calls.append(("insert", kw))
        return self

    def bind(self, **kw):
        self.calls.append(("bind", kw))
        return self

    def transition(self, **kw):
        self.calls.append(("transition", kw))
        return self

    def execute(self):
        return {"id": "bc_001"}


def test_モニターストリームを無効にして枠を作る(tmp_path):
    """`enableMonitorStream` の既定は true で、その場合 YouTube は
    **testing 状態の経由を必須にする**（公式ドキュメント: true なら必須で経由、
    false なら経由不可）。このデーモンは testing を通らず ready から live へ
    直行するので、既定のままだと transition が 403 invalidTransition で拒否される。

    実測（2026-09-09）: 枠 lzt1loCYxWM が monitor=True で作られ、
    ready のまま live に遷移できずに配信が始まらなかった。
    """
    from scripts.run_live import start_broadcast
    yt = _FakeYouTube()
    start_broadcast(yt, "st_1", "テスト", now=T0, state_path=tmp_path / "live.json")
    body = next(kw["body"] for name, kw in yt.calls if name == "insert")
    assert body["contentDetails"]["monitorStream"]["enableMonitorStream"] is False


def test_枠を作ると状態に書かれる(tmp_path):
    from scripts.run_live import start_broadcast
    state = tmp_path / "live.json"
    got = start_broadcast(_FakeYouTube(), "st_1", "テスト", now=T0, state_path=state)
    assert got == "bc_001"
    assert json.loads(state.read_text(encoding="utf-8"))["broadcast_id"] == "bc_001"


def test_配信中にもう一度呼ぶと止まる(tmp_path):
    """呼び出し側ではなくこの関数の中で止めること。
    直接叩く経路が素通りすると2本同時配信になる。"""
    from scripts.run_live import AlreadyStreaming, start_broadcast
    state = tmp_path / "live.json"
    start_broadcast(_FakeYouTube(), "st_1", "1本目", now=T0, state_path=state)
    with pytest.raises(AlreadyStreaming):
        start_broadcast(_FakeYouTube(), "st_1", "2本目", now=T0, state_path=state)


def test_枠を終了すると状態のliveが下りる(tmp_path):
    from scripts.run_live import complete_broadcast, start_broadcast
    state = tmp_path / "live.json"
    yt = _FakeYouTube()
    start_broadcast(yt, "st_1", "1本目", now=T0, state_path=state)
    got = complete_broadcast(yt, state_path=state)
    assert got == "bc_001"
    assert json.loads(state.read_text(encoding="utf-8"))["live"] is False


def test_終了したあとなら次の枠を作れる(tmp_path):
    from scripts.run_live import complete_broadcast, start_broadcast
    state = tmp_path / "live.json"
    yt = _FakeYouTube()
    start_broadcast(yt, "st_1", "1本目", now=T0, state_path=state)
    complete_broadcast(yt, state_path=state)
    start_broadcast(yt, "st_1", "2本目", now=T0, state_path=state)   # 例外が出ないこと


def test_配信中の枠が無ければ終了は何もしない(tmp_path):
    from scripts.run_live import complete_broadcast
    assert complete_broadcast(_FakeYouTube(), state_path=tmp_path / "live.json") is None


# ---------------------------------------------------------- loop.mp4 の日次差し替え

def test_日付が変わっていれば作り直す():
    from scripts.run_live import should_rebuild
    assert should_rebuild(datetime(2026, 9, 8, 23, 0), datetime(2026, 9, 9, 6, 0))


def test_同じ日なら作り直さない():
    from scripts.run_live import should_rebuild
    assert not should_rebuild(datetime(2026, 9, 9, 0, 0), datetime(2026, 9, 9, 23, 0))


def test_一度も作っていなければ作る():
    from scripts.run_live import should_rebuild
    assert should_rebuild(None, datetime(2026, 9, 9, 6, 0))


def test_再構築の書き出し先はloop_mp4そのものではない():
    """配信中の ffmpeg が loop.mp4 を開いたままなので、そこには直接書けない
    （Windows では書き込みが失敗する）。ビルドは別名に対して行い、
    終わってから os.replace で差し替える。"""
    from scripts.run_live import LOOP_MP4, _rebuild_target
    next_path = _rebuild_target(LOOP_MP4)
    assert next_path != LOOP_MP4
    assert next_path.parent == LOOP_MP4.parent


# ------------------------------------------------- R6c: 再構築はローテーション時だけ

def test_ローテーションが起きていなければ日付が変わっていても作り直さない():
    """R6cの回帰対策。このティックでローテーションが起きていないなら、
    たとえ日付が変わっていても再構築を始めてはいけない。ここで始めると、
    重いビルドの間ずっと古い配信枠が生き延び、12時間の壁を越えて
    アーカイブを丸ごと失いかねない。"""
    from scripts.run_live import should_rebuild_on_rotation
    assert not should_rebuild_on_rotation(
        False, datetime(2026, 9, 8, 23, 0), datetime(2026, 9, 9, 6, 0))


def test_ローテーションが起きたティックで日付が変わっていれば作り直す():
    from scripts.run_live import should_rebuild_on_rotation
    assert should_rebuild_on_rotation(
        True, datetime(2026, 9, 8, 23, 0), datetime(2026, 9, 9, 6, 0))


def test_ローテーションが起きても同じ日なら作り直さない():
    from scripts.run_live import should_rebuild_on_rotation
    assert not should_rebuild_on_rotation(
        True, datetime(2026, 9, 9, 0, 0), datetime(2026, 9, 9, 23, 0))


def test_ローテーションが起きて一度も作っていなければ作る():
    from scripts.run_live import should_rebuild_on_rotation
    assert should_rebuild_on_rotation(True, None, datetime(2026, 9, 9, 6, 0))


# ------------------------------------------------- ingest が active になるまで待つ

def test_activeになるまで待ってから枠を作る():
    """transition(live) はバインドしたストリームが active でないと
    errorStreamInactive で落ちる。ffmpeg を起こした直後は未登録なので、
    待たずに transition すると初回はまず失敗する。"""
    slept = []
    yt = _FakeYouTube(stream_statuses=["inactive", "inactive", "active"])
    wait_for_stream_active(yt, "st_1", poll_seconds=5, sleep=slept.append)
    assert slept == [5, 5]
    assert yt.streams.calls == 3


def test_activeにならなければ例外で止まる():
    ticks = iter([0.0, 10.0, 20.0, 30.0, 40.0])
    yt = _FakeYouTube(stream_statuses=["inactive"])
    with pytest.raises(StreamNotActive):
        wait_for_stream_active(yt, "st_1", timeout_seconds=15,
                               poll_seconds=5, sleep=lambda s: None,
                               clock=lambda: next(ticks))


def test_activeを待つのは枠を作る関数の中(tmp_path, monkeypatch):
    """呼び出し側に置くと、直接叩く経路が errorStreamInactive で落ちる。
    active になっていなければ insert まで到達しないこと。"""
    import scripts.run_live as m
    monkeypatch.setattr(m, "STREAM_ACTIVE_TIMEOUT", 0.0)
    monkeypatch.setattr(m, "STREAM_POLL_SECONDS", 0.0)
    yt = _FakeYouTube(stream_statuses=["inactive"])
    with pytest.raises(StreamNotActive):
        m.start_broadcast(yt, "st_1", "テスト", now=T0,
                          state_path=tmp_path / "live.json")
    assert yt.calls == []                     # insert / bind / transition のどれも呼ばれない
    assert not (tmp_path / "live.json").exists()


# ------------------------------------------------------------ ffmpeg の再起動上限

def test_窓の中で上限を超えたら止める():
    """loop.mp4 が壊れていると ffmpeg は即落ちする。上限が無いと11.5時間ぶん
    再起動を繰り返し、配信枠は live のまま映像が一度も届かない。"""
    now = T0
    restarts = []
    for i in range(FFMPEG_RESTART_LIMIT):
        restarts = record_restart(restarts, now + timedelta(seconds=60 * i))
        assert not too_many_restarts(restarts)
    restarts = record_restart(restarts, now + timedelta(seconds=60 * FFMPEG_RESTART_LIMIT))
    assert too_many_restarts(restarts)


def test_窓の外に出た再起動は数えない():
    """散発的な再起動でデーモンを止めない。数えるのは窓の中だけ。"""
    restarts = []
    for i in range(FFMPEG_RESTART_LIMIT * 3):
        restarts = record_restart(restarts, T0 + FFMPEG_RESTART_WINDOW * i)
        assert not too_many_restarts(restarts)


# ------------------------------------------------------------------- CLI の入口

def test_stopは配信枠を終了して終わる(monkeypatch):
    """落ちたあと state/live.json には live: true が残り、次の起動は
    AlreadyStreaming で止まる。手で state を書き換えずに戻せる出口が要る。"""
    import scripts.run_live as m
    called = []
    monkeypatch.setattr(m, "get_service", lambda: "yt")
    monkeypatch.setattr(m, "complete_broadcast", lambda yt: called.append(yt) or "bc_9")
    monkeypatch.setattr(m, "_run_forever", lambda *a, **k: pytest.fail("配信を始めてはいけない"))
    m.main(["--stop"])
    assert called == ["yt"]


def test_dry_runは配信枠もffmpegも作らない(monkeypatch, tmp_path, capsys):
    import scripts.run_live as m
    loop = tmp_path / "loop.mp4"
    loop.write_bytes(b"")
    monkeypatch.setattr(m, "LOOP_MP4", loop)
    monkeypatch.setattr(m, "select_recipes", lambda d, *, exclude_categories: [{"id": "a"}])
    monkeypatch.setattr(m, "_run_forever", lambda *a, **k: pytest.fail("配信を始めてはいけない"))
    m.main(["--dry-run"])
    assert "公開されません" in capsys.readouterr().out


def test_loop_mp4が無ければ配信を始めない(monkeypatch, tmp_path):
    """先に YouTube API を叩いてから落ちると、原因が分かりにくいうえに
    枠だけが残る。"""
    import scripts.run_live as m
    monkeypatch.setattr(m, "LOOP_MP4", tmp_path / "ない.mp4")
    monkeypatch.setattr(m, "_run_forever", lambda *a, **k: pytest.fail("配信を始めてはいけない"))
    with pytest.raises(SystemExit, match="loop"):
        m.main([])


def test_除外カテゴリはプロセスの間ずっと効く(monkeypatch, tmp_path):
    """デーモンは日付が変わるたびに loop.mp4 を作り直す。ここに除外が
    渡っていないと、投票日に作った除外つきループが最初のローテーションで
    除外なしのループに差し替わる。"""
    import scripts.run_live as m
    loop = tmp_path / "loop.mp4"
    loop.write_bytes(b"")
    monkeypatch.setattr(m, "LOOP_MP4", loop)
    got = []
    monkeypatch.setattr(m, "_run_forever", lambda exclude: got.append(exclude))
    m.main(["--exclude-category", "election"])
    assert got == [frozenset({"election"})]


def test_再構築は除外を付けたまま呼ぶ(monkeypatch, tmp_path):
    """日次の作り直しが除外を落とすと、投票日の除外は最初のローテーションで
    消える。除外の指定はビルドまで届いていること。"""
    import scripts.run_live as m
    got = {}
    monkeypatch.setattr(m, "select_recipes",
                        lambda d, *, exclude_categories: got.setdefault(
                            "exclude", exclude_categories) or [{"id": "a"}])
    monkeypatch.setattr(m, "build", lambda path, recipes, *, day: path)
    m.rebuild_loop(tmp_path / "loop.next.mp4", frozenset({"election"}))
    assert got["exclude"] == frozenset({"election"})


def test_再構築のシャッフルの種はUTCの日付(monkeypatch, tmp_path):
    """再構築の引き金（should_rebuild）は UTC の日付を見ている。種だけ
    ローカル日付（build の既定の date.today()）だと両者がずれ、JST では
    20:00 UTC の再構築と約11時間半後の 07:30 UTC の再構築が同じ日付の種を
    引く。結果、続けて2本まったく同じ並びのループが流れる。"""
    import scripts.run_live as m
    got = {}

    def _fake_build(path, recipes, *, day):
        got["day"] = day
        return path

    monkeypatch.setattr(m, "select_recipes",
                        lambda d, *, exclude_categories: [{"id": "a"}])
    monkeypatch.setattr(m, "build", _fake_build)
    m.rebuild_loop(tmp_path / "loop.next.mp4", frozenset())
    assert got["day"] == datetime.now(timezone.utc).date()
