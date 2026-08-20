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


def test_翌日の枠を先に作れる():
    # 手で起動する運用では、夜に翌朝の分を用意したいことがある。
    # 当日の枠が過ぎていると days_ahead=0 では何も返らず、何も作れない。
    from datetime import datetime

    from scripts.slots import pending_slots

    got = pending_slots(datetime(2026, 8, 12, 20, 0), days_ahead=1)

    assert [s.strftime("%m-%d %H:%M") for s in got] == ["08-13 07:30", "08-13 18:30"]


def test_翌日指定でも過ぎた枠は返さない():
    from datetime import datetime

    from scripts.slots import pending_slots

    # 翌日の朝の枠より後（＝ありえないが、境界の挙動を固定しておく）
    got = pending_slots(datetime(2026, 8, 13, 12, 0), days_ahead=0)

    assert [s.strftime("%H:%M") for s in got] == ["18:30"]


# ── 長尺の枠（1日1本・18:00）─────────────────────────────────

def test_長尺の枠は18時ちょうどの1つだけ返る():
    got = pending_slots(datetime(2026, 8, 20, 10, 0, tzinfo=JST), kind="long")
    assert got == [datetime(2026, 8, 20, 18, 0, tzinfo=JST)]


def test_既定はショートのままで長尺の枠は混ざらない():
    # 既存の呼び出し（run_daily.py）は kind を渡さない。長尺の枠が
    # 混ざるとショートが 18:00 に載り、1日1本という長尺の約束も崩れる。
    got = pending_slots(datetime(2026, 8, 20, 6, 0, tzinfo=JST))
    assert got == [datetime(2026, 8, 20, 7, 30, tzinfo=JST),
                   datetime(2026, 8, 20, 18, 30, tzinfo=JST)]


def test_長尺も過ぎた枠は遡らない():
    assert pending_slots(datetime(2026, 8, 20, 18, 0, tzinfo=JST),
                         kind="long") == []


def test_長尺も翌日ぶんを先に作れる():
    got = pending_slots(datetime(2026, 8, 20, 20, 0, tzinfo=JST),
                        days_ahead=1, kind="long")
    assert [s.strftime("%m-%d %H:%M") for s in got] == ["08-21 18:00"]


def test_知らない種別は取り違えずに落とす():
    # 綴り間違い（"longform" 等）を黙って空リストにすると、その日は
    # 何も作らずに正常終了する。0本の理由が枠の綴りだったと後から
    # 気づけないので、その場で止める。
    import pytest
    with pytest.raises(ValueError):
        pending_slots(datetime(2026, 8, 20, 10, 0, tzinfo=JST), kind="longform")
