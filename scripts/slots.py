#!/usr/bin/env python3
"""投稿枠の計算。

1日2本を JST 07:30 と 18:30 に予約公開する。
起動時にまだ来ていない枠だけを返し、**過ぎた枠は遡って埋めない**。
古いニュースを後から出しても伸びず、量産型の印象を強めるだけなので。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

PUBLISH_SLOTS = (time(7, 30), time(18, 30))


def pending_slots(now: datetime, days_ahead: int = 0) -> list[datetime]:
    """まだ来ていない枠を、早い順に返す。

    `days_ahead` は何日先の枠を見るか。0 なら当日の残り、1 なら翌日の
    2枠すべて。**手で起動する運用**では、夜に翌朝の分を作っておきたい
    ことがある（当日の枠が過ぎていると 0 では何も返らず、何も作れない）。

    返す枠は now と同じタイムゾーン（naive なら naive、aware ならそのまま）。
    combine に tzinfo を渡さないと aware な now と naive な枠を比較して
    TypeError になるうえ、呼び出し側が枠を ISO8601 に整形したときに
    タイムゾーンが落ちる。run_daily.py は JST を明示して呼ぶ。
    """
    day = now.date() + timedelta(days=days_ahead)
    return [
        slot
        for slot in (datetime.combine(day, t, tzinfo=now.tzinfo)
                     for t in PUBLISH_SLOTS)
        if slot > now
    ]
