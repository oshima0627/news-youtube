#!/usr/bin/env python3
"""24時間のライブ配信を回す。ffmpeg は止めず、配信枠だけを差し替える。

  python scripts/run_live.py
"""

from __future__ import annotations

import json
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


class AlreadyStreaming(RuntimeError):
    """すでに配信中の枠がある。二重起動すると2本同時配信になる。"""


def _read_state(state_path: Path) -> dict:
    if not Path(state_path).exists():
        return {}
    return json.loads(Path(state_path).read_text(encoding="utf-8"))


def _write_state(state_path: Path, data: dict) -> None:
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def start_broadcast(youtube, stream_id: str, title: str, *,
                    now: datetime, state_path: Path = STATE) -> str:
    """配信枠を1つ作り、ストリームに結び付けて live にする。

    **関門はこの関数の中にある。** 呼び出し側に移さないこと。
    キューのフィルタ側にだけ置いた結果、直接叩く経路が素通りした前例がある
    （known-issues 2・3・8番、`upload_tiktok.post()` と同型）。
    """
    state = _read_state(state_path)
    if state.get("broadcast_id") and state.get("live"):
        raise AlreadyStreaming(
            f"配信中の枠があります: {state['broadcast_id']}"
            f"（開始 {state.get('started_at')}）")

    body = {
        "snippet": {"title": title,
                    "scheduledStartTime": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        # 自動で終わられるとローテーションの制御を失う
        "contentDetails": {"enableAutoStart": False, "enableAutoStop": False},
    }
    broadcast_id = youtube.liveBroadcasts().insert(
        part="snippet,status,contentDetails", body=body).execute()["id"]
    youtube.liveBroadcasts().bind(
        part="id,contentDetails", id=broadcast_id, streamId=stream_id).execute()
    youtube.liveBroadcasts().transition(
        part="id,status", id=broadcast_id, broadcastStatus="live").execute()

    _write_state(state_path, {"broadcast_id": broadcast_id, "stream_id": stream_id,
                              "started_at": now.isoformat(), "live": True})
    return broadcast_id
