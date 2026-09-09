"""24時間ライブ配信の関門のテスト。

守りたいのは2つ: **12時間を超えたら例外で止まる**（アーカイブが作られず
再生時間が丸ごと0になる）ことと、**二重起動ロックが枠を作る関数の中に
あって呼び出し側からは外せない**こと。
"""

import json
from datetime import datetime, timedelta

import pytest

from scripts.run_live import (HARD_LIMIT, ROTATE_AFTER, ArchiveWindowExceeded,
                              assert_within_archive_window, should_rotate)

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


# ---------------------------------------------------------------- 枠の管理

class _FakeYouTube:
    """liveBroadcasts.insert / bind / transition の最小の身代わり。"""

    def __init__(self):
        self.calls = []

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
