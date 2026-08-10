from datetime import datetime, timedelta, timezone

from scripts.slots import pending_slots

JST = timezone(timedelta(hours=9))


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


def test_タイムゾーン付きのnowを渡すと枠も同じタイムゾーンで返る():
    # run_daily.py は JST を明示して呼ぶ。combine に tzinfo を渡していないと
    # naive な枠と aware な now の比較で TypeError になる。
    got = pending_slots(datetime(2026, 8, 11, 6, 0, tzinfo=JST))
    assert got == [datetime(2026, 8, 11, 7, 30, tzinfo=JST),
                   datetime(2026, 8, 11, 18, 30, tzinfo=JST)]


def test_タイムゾーン付きの枠はISO8601にオフセット付きで整形できる():
    # run_daily.py は slot.isoformat() をそのまま --schedule に渡す。
    # タイムゾーンが落ちると YouTube 側の予約がUTC扱いになり9時間ずれる。
    got = pending_slots(datetime(2026, 8, 11, 6, 0, tzinfo=JST))
    assert got[0].isoformat() == "2026-08-11T07:30:00+09:00"
