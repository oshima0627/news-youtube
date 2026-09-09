"""24時間ライブ配信の関門のテスト。

守りたいのは2つ: **12時間を超えたら例外で止まる**（アーカイブが作られず
再生時間が丸ごと0になる）ことと、**二重起動ロックが枠を作る関数の中に
あって呼び出し側からは外せない**こと。
"""

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
