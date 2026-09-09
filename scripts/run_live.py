#!/usr/bin/env python3
"""24時間のライブ配信を回す。ffmpeg は止めず、配信枠だけを差し替える。

  python scripts/run_live.py
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "live.json"

# アーカイブは12時間未満の配信でしか作られない（YouTube公式ヘルプ）。
# 超えた瞬間、その配信の再生時間は1分も4,000時間に入らない。
HARD_LIMIT = timedelta(hours=12)
# 30分のマージン。API の一時的な失敗で1回分を丸ごと失わないため。
ROTATE_AFTER = timedelta(hours=11, minutes=30)


class ArchiveWindowExceeded(RuntimeError):
    """12時間に達した。この配信のアーカイブはもう作られない。"""


def should_rotate(started_at: datetime, now: datetime) -> bool:
    return now - started_at >= ROTATE_AFTER


def assert_within_archive_window(started_at: datetime, now: datetime) -> None:
    if now - started_at >= HARD_LIMIT:
        raise ArchiveWindowExceeded(
            f"配信開始から {now - started_at} 経過。アーカイブが作られません。")
