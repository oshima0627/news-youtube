"""TikTok 投稿キューの単体テスト。

TikTok の Direct Post API には予約投稿が無いので、「YouTube の枠と同じ時刻に
投げる」をキュー＋定時タスクで作る。ここが壊れると、投稿されない（枠を落とす）か
二重投稿になる。state/published.json と同じ性質のファイルなので、
重複防止と順序を全部縛る。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import tiktok_queue as q

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=JST)


@pytest.fixture
def state(tmp_path):
    return tmp_path


def test_積んだものを枠の時刻を過ぎたら取り出せる(state):
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=1))
    assert [e["workdir"] for e in q.due_entries(state, NOW)] == ["work/abc/tiktok"]


def test_枠の時刻がまだ来ていないものは取り出さない(state):
    q.enqueue(state, "work/abc/tiktok", NOW + timedelta(hours=1))
    assert q.due_entries(state, NOW) == []


def test_枠の時刻ちょうどは取り出す(state):
    q.enqueue(state, "work/abc/tiktok", NOW)
    assert len(q.due_entries(state, NOW)) == 1


def test_早い枠から順に返す(state):
    q.enqueue(state, "work/late/tiktok", NOW - timedelta(hours=1))
    q.enqueue(state, "work/early/tiktok", NOW - timedelta(hours=5))
    assert [e["workdir"] for e in q.due_entries(state, NOW)] == [
        "work/early/tiktok", "work/late/tiktok"]


def test_同じworkdirを二重に積まない(state):
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=1))
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=2))
    assert len(q.due_entries(state, NOW)) == 1


def test_投稿済みにしたものはもう取り出さない(state):
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=1))
    q.mark_posted(state, "work/abc/tiktok",
                  {"publish_id": "p1", "privacy_level": "PUBLIC_TO_EVERYONE"})
    assert q.due_entries(state, NOW) == []


def test_投稿済みのworkdirは積み直しても取り出さない(state):
    """同じ題材で run_daily を2回まわしても、TikTokに2本並ばないこと。"""
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=1))
    q.mark_posted(state, "work/abc/tiktok", {"publish_id": "p1"})
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=1))
    assert q.due_entries(state, NOW) == []


def test_投稿済みの記録には結果が残る(state):
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=1))
    q.mark_posted(state, "work/abc/tiktok",
                  {"publish_id": "p1", "privacy_level": "PUBLIC_TO_EVERYONE"})
    posted = q.load_posted(state)
    assert posted["work/abc/tiktok"]["publish_id"] == "p1"
    assert posted["work/abc/tiktok"]["privacy_level"] == "PUBLIC_TO_EVERYONE"


def test_キューが無いときは空を返す(state):
    assert q.due_entries(state, NOW) == []


def test_枠の時刻はタイムゾーン付きで往復する(state):
    q.enqueue(state, "work/abc/tiktok", NOW - timedelta(hours=1))
    due = datetime.fromisoformat(q.due_entries(state, NOW)[0]["due"])
    assert due.utcoffset() == timedelta(hours=9)


def test_枠の時刻が壊れていても他の投稿を巻き込まない(state):
    """1件の壊れた記録で、その日の投稿が全部止まらないこと。"""
    q.enqueue(state, "work/good/tiktok", NOW - timedelta(hours=1))
    data = q.load_queue(state)
    data.append({"workdir": "work/broken/tiktok", "due": "ぐちゃぐちゃ"})
    q.save_queue(state, data)
    assert [e["workdir"] for e in q.due_entries(state, NOW)] == ["work/good/tiktok"]
