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
    """now の時点でまだ来ていない当日の枠を、早い順に返す。"""
    return [
        datetime.combine(now.date(), t)
        for t in PUBLISH_SLOTS
        if datetime.combine(now.date(), t) > now
    ]
