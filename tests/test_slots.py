from datetime import datetime

from scripts.slots import pending_slots


def test_早朝起動なら当日2枠とも返る():
    got = pending_slots(datetime(2026, 8, 11, 6, 0))
    assert got == [datetime(2026, 8, 11, 7, 30), datetime(2026, 8, 11, 18, 30)]


def test_昼に起動したら夕方の枠だけ返る():
    got = pending_slots(datetime(2026, 8, 11, 12, 0))
    assert got == [datetime(2026, 8, 11, 18, 30)]


def test_夕方の枠を過ぎたら空になる():
    # 過去分は遡って埋めない。古いニュースを今出しても伸びない
    assert pending_slots(datetime(2026, 8, 11, 19, 0)) == []


def test_枠の時刻ちょうどは過ぎたものとして扱う():
    # 予約公開は未来時刻でないと受け付けられない
    assert pending_slots(datetime(2026, 8, 11, 7, 30)) == [
        datetime(2026, 8, 11, 18, 30)
    ]
