"""定時タスク（post_tiktok_due.run）の単体テスト。

07:25 / 18:25 に無人で起きる経路なので、**失敗の分類**が全部。
題材ごとの失敗（動画が無い等）で残りを落とさず、環境ごとの失敗
（未審査・認証切れ）はどの動画でも同じ理由で失敗するのでその場で止める。
run_daily.py がチャンネル取り違えを扱っている判断と同じ。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import post_tiktok_due as due
from scripts import tiktok, tiktok_queue

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 2, 18, 25, tzinfo=JST)


@pytest.fixture
def state(tmp_path):
    return tmp_path


def _queue(state, *workdirs, offset_hours=-1):
    for w in workdirs:
        tiktok_queue.enqueue(state, w, NOW + timedelta(hours=offset_hours))


def test_枠が来たものを投稿して記録する(state):
    _queue(state, "work/a/tiktok")
    posted = []

    def fake_post(workdir, **kw):
        posted.append(workdir)
        return {"publish_id": "p1", "privacy_level": "PUBLIC_TO_EVERYONE"}

    assert due.run(state, NOW, fake_post) == 1
    assert posted == ["work/a/tiktok"]
    assert "work/a/tiktok" in tiktok_queue.load_posted(state)


def test_枠が来ていないものは投稿しない(state):
    _queue(state, "work/a/tiktok", offset_hours=+1)
    assert due.run(state, NOW, lambda w, **kw: pytest.fail("投稿してはいけない")) == 0


def test_1本が題材固有の理由で失敗しても残りを投稿する(state):
    _queue(state, "work/a/tiktok", "work/b/tiktok")
    tried = []

    def fake_post(workdir, **kw):
        tried.append(workdir)
        if workdir == "work/a/tiktok":
            raise tiktok.TikTokError("video.mp4 がありません")
        return {"publish_id": "p2"}

    assert due.run(state, NOW, fake_post) == 1
    assert tried == ["work/a/tiktok", "work/b/tiktok"]


def test_失敗した1本は投稿済みにしない(state):
    _queue(state, "work/a/tiktok")

    def fake_post(workdir, **kw):
        raise tiktok.TikTokError("video.mp4 がありません")

    due.run(state, NOW, fake_post)
    assert tiktok_queue.load_posted(state) == {}


def test_失敗した1本はキューに残る(state):
    """作り直して次の枠で出せるように。"""
    _queue(state, "work/a/tiktok")

    def fake_post(workdir, **kw):
        raise tiktok.TikTokError("video.mp4 がありません")

    due.run(state, NOW, fake_post)
    assert [e["workdir"] for e in tiktok_queue.load_queue(state)] == ["work/a/tiktok"]


def test_未審査なら残りを試さずその場で止める(state):
    """どの動画でも同じ理由で失敗する。全件ぶん同じ失敗を繰り返さない。"""
    _queue(state, "work/a/tiktok", "work/b/tiktok")
    tried = []

    def fake_post(workdir, **kw):
        tried.append(workdir)
        raise tiktok.NotAudited("公開が選べません")

    with pytest.raises(tiktok.NotAudited):
        due.run(state, NOW, fake_post)
    assert tried == ["work/a/tiktok"]


def test_アカウント取り違えなら残りを試さずその場で止める(state):
    _queue(state, "work/a/tiktok", "work/b/tiktok")
    tried = []

    def fake_post(workdir, **kw):
        tried.append(workdir)
        raise tiktok.AccountMismatch("違うアカウントです")

    with pytest.raises(tiktok.AccountMismatch):
        due.run(state, NOW, fake_post)
    assert tried == ["work/a/tiktok"]


def test_尺不足は題材固有なので残りを続ける(state):
    _queue(state, "work/a/tiktok", "work/b/tiktok")
    tried = []

    def fake_post(workdir, **kw):
        tried.append(workdir)
        if workdir == "work/a/tiktok":
            raise tiktok.VideoTooShort("58.4秒")
        return {"publish_id": "p2"}

    assert due.run(state, NOW, fake_post) == 1
    assert len(tried) == 2


def test_キューが空なら何もしない(state):
    assert due.run(state, NOW, lambda w, **kw: pytest.fail("投稿してはいけない")) == 0
