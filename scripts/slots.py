#!/usr/bin/env python3
"""投稿枠の計算。

1日2本を JST 07:30 と 18:30 に予約公開する。
起動時にまだ来ていない枠だけを返し、**過ぎた枠は遡って埋めない**。
古いニュースを後から出しても伸びず、量産型の印象を強めるだけなので。
"""

from __future__ import annotations

from datetime import datetime, time

PUBLISH_SLOTS = (time(7, 30), time(18, 30))


def pending_slots(now: datetime) -> list[datetime]:
    """now の時点でまだ来ていない当日の枠を、早い順に返す。

    返す枠は now と同じタイムゾーン（naive なら naive、aware ならそのまま）。
    combine に tzinfo を渡さないと aware な now と naive な枠を比較して
    TypeError になるうえ、呼び出し側が枠を ISO8601 に整形したときに
    タイムゾーンが落ちる。run_daily.py は JST を明示して呼ぶ。
    """
    return [
        slot
        for slot in (datetime.combine(now.date(), t, tzinfo=now.tzinfo)
                     for t in PUBLISH_SLOTS)
        if slot > now
    ]
