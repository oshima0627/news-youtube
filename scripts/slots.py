#!/usr/bin/env python3
"""投稿枠の計算。

ショートは1日2本を JST 07:30 と 18:30、長尺は1日1本を JST 18:00 に予約公開する。
起動時にまだ来ていない枠だけを返し、**過ぎた枠は遡って埋めない**。
古いニュースを後から出しても伸びず、量産型の印象を強めるだけなので。

枠を形式ごとに分けているのは、長尺とショートが同じ枠を取り合うと
「長尺は1日1本」という約束を枠の側で守れなくなるため。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

SHORT_SLOTS = (time(7, 30), time(18, 30))
LONG_SLOTS = (time(18, 0),)

# 既存の呼び出し（run_daily.py・テスト）が参照している名前。ショートの枠を指す。
PUBLISH_SLOTS = SHORT_SLOTS

SLOTS_BY_KIND = {"short": SHORT_SLOTS, "long": LONG_SLOTS}


def pending_slots(now: datetime, days_ahead: int = 0,
                  kind: str = "short") -> list[datetime]:
    """まだ来ていない枠を、早い順に返す。

    `kind` は動画の形式（"short" / "long"）。既定がショートなのは、
    既存の呼び出しを1文字も変えずに現在の挙動を保つため。
    綴りを間違えた種別は空リストではなく ValueError で落とす — 空を返すと
    「その日は枠が無かった」と区別が付かず、0本の理由が綴り間違いだったと
    後から気づけない。

    `days_ahead` は何日先の枠を見るか。0 なら当日の残り、1 なら翌日の
    2枠すべて。**手で起動する運用**では、夜に翌朝の分を作っておきたい
    ことがある（当日の枠が過ぎていると 0 では何も返らず、何も作れない）。

    返す枠は now と同じタイムゾーン（naive なら naive、aware ならそのまま）。
    combine に tzinfo を渡さないと aware な now と naive な枠を比較して
    TypeError になるうえ、呼び出し側が枠を ISO8601 に整形したときに
    タイムゾーンが落ちる。run_daily.py は JST を明示して呼ぶ。
    """
    try:
        slots = SLOTS_BY_KIND[kind]
    except KeyError:
        raise ValueError(
            f"知らない形式です: {kind!r}（{'/'.join(SLOTS_BY_KIND)} のいずれか）"
        ) from None

    day = now.date() + timedelta(days=days_ahead)
    return [
        slot
        for slot in (datetime.combine(day, t, tzinfo=now.tzinfo)
                     for t in slots)
        if slot > now
    ]
