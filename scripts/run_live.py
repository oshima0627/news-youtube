#!/usr/bin/env python3
"""24時間のライブ配信を回す。ffmpeg は止めず、配信枠だけを差し替える。

  python scripts/run_live.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.upload_youtube import get_service  # noqa: E402

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


def should_rebuild(last_built: datetime | None, now: datetime) -> bool:
    """loop.mp4 を作り直すか。1日1回だけ。

    新しい loop.mp4 は ffmpeg を再起動しないと反映されないので、
    ローテーションのうち日付が変わって最初の1回だけで入れ替える。
    """
    if last_built is None:
        return True
    return last_built.date() < now.date()


def should_rebuild_on_rotation(rotated: bool, last_built: datetime | None,
                               now: datetime) -> bool:
    """このティックで再構築するか（R6c）。**ローテーションが起きたティックに限る。**

    再構築は1時間を超えることもある重い処理。ローテーションが起きた直後の
    ティックだけに絞ることで、ビルドを始める時点の新しい配信枠の壁時計は
    必ずほぼ0になり、次のローテーションまでの `ROTATE_AFTER`
    （11時間半）がまるごと余裕として残る。ここを外して「日付が変わった
    ティックなら常に」にすると、古い配信枠が
    `ROTATE_AFTER + ビルド時間` だけ生き延びてしまい、`ROTATE_AFTER` と
    `HARD_LIMIT` の間の30分のマージンでは吸収しきれず12時間の壁を
    越えてアーカイブを失いかねない。
    """
    return rotated and should_rebuild(last_built, now)


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


def complete_broadcast(youtube, *, state_path: Path = STATE) -> str | None:
    """配信中の枠を終了してアーカイブを確定させる。無ければ None。"""
    state = _read_state(state_path)
    broadcast_id = state.get("broadcast_id")
    if not broadcast_id or not state.get("live"):
        return None
    youtube.liveBroadcasts().transition(
        part="id,status", id=broadcast_id, broadcastStatus="complete").execute()
    state["live"] = False
    _write_state(state_path, state)
    return broadcast_id


def ensure_stream(youtube) -> tuple[str, str]:
    """再利用可能なストリームを1本用意し、(stream_id, ストリームキー) を返す。

    キーは固定。ffmpeg はこのキーに向けて流し続け、枠だけが差し替わる。
    """
    existing = youtube.liveStreams().list(
        part="id,cdn", mine=True, maxResults=50).execute().get("items", [])
    for item in existing:
        if item["cdn"].get("ingestionType") == "rtmp":
            return item["id"], item["cdn"]["ingestionInfo"]["streamName"]
    created = youtube.liveStreams().insert(part="snippet,cdn", body={
        "snippet": {"title": "news-radio"},
        "cdn": {"frameRate": "30fps", "resolution": "1080p",
                "ingestionType": "rtmp"},
    }).execute()
    return created["id"], created["cdn"]["ingestionInfo"]["streamName"]


RTMP_BASE = "rtmp://a.rtmp.youtube.com/live2"
LOOP_MP4 = ROOT / "work" / "live" / "loop.mp4"


def _rebuild_target(loop_path: Path) -> Path:
    """再構築した loop.mp4 を書き出す先。**`loop_path` そのものではない。**

    配信中の ffmpeg がまだ `loop_path` を開いたまま流しているので、
    そこに直接書こうとすると Windows では書き込みが失敗する。ビルドが
    終わったあと `os.replace` で `loop_path` に差し替える。
    """
    return loop_path.with_suffix(".next.mp4")


def _spawn_ffmpeg(key: str) -> subprocess.Popen:
    """loop.mp4 を無限ループで RTMP に流す。**再エンコードしない。**"""
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-re", "-stream_loop", "-1", "-fflags", "+genpts",
        "-i", str(LOOP_MP4), "-c", "copy", "-f", "flv", f"{RTMP_BASE}/{key}",
    ])


def main() -> None:
    youtube = get_service()
    stream_id, key = ensure_stream(youtube)
    proc = _spawn_ffmpeg(key)
    started = datetime.now(timezone.utc)
    last_built = datetime.now(timezone.utc)
    start_broadcast(youtube, stream_id,
                    f"ニュースラジオ {started:%Y-%m-%d %H:%M} UTC", now=started)
    try:
        while True:
            time.sleep(60)
            now = datetime.now(timezone.utc)
            if proc.poll() is not None:                 # ffmpeg が落ちた
                proc = _spawn_ffmpeg(key)
            # 枠を切り替えられないまま12時間に達したら、配信ごと止める。
            # 続けてアーカイブを丸ごと失うより、止めて11時間分を確定させる方が得。
            assert_within_archive_window(started, now)
            rotated = False
            if should_rotate(started, now):
                # ここは高速に保つ。重いビルドをこの中に置くと、古い配信枠が
                # ROTATE_AFTER + ビルド時間だけ生き延びてしまい、
                # ROTATE_AFTER と HARD_LIMIT の間の30分のマージン
                # （API の一時的な失敗を吸収するためのもの）では足りず、
                # 12時間の壁を越えてアーカイブを丸ごと失いかねない（R6c）。
                complete_broadcast(youtube)
                started = datetime.now(timezone.utc)
                start_broadcast(youtube, stream_id,
                                f"ニュースラジオ {started:%Y-%m-%d %H:%M} UTC",
                                now=started)
                rotated = True
            if should_rebuild_on_rotation(rotated, last_built, now):
                # ローテーションが起きたティックに限るので、いま started
                # した配信枠の壁時計はほぼ0。ここで再構築（1時間を超える
                # こともある）をしている間は、たった今立ち上げた ffmpeg が
                # 古い loop.mp4 をそのまま流し続ける。
                #
                # 新しい loop.mp4 は古い ffmpeg がまだ配信中のうちに、
                # 別名で作っておく（LOOP_MP4 に直接書こうとすると、
                # Windows では配信中の ffmpeg がファイルを開いたままで
                # 書き込みが失敗する）。
                next_path = _rebuild_target(LOOP_MP4)
                from scripts.build_live_loop import (RECIPES_DIR, build,
                                                     select_recipes)
                try:
                    build(next_path, select_recipes(RECIPES_DIR))
                except Exception as e:
                    # 再構築に失敗しても配信は止めない。今日はもう1回
                    # このループで留守番し、次のローテーションで再挑戦する
                    # （last_built を更新していないので should_rebuild は
                    # 引き続き True を返す）。失敗が理由で watch-hours の
                    # 蓄積を止めるほうが損失が大きい。
                    print(f"! loop.mp4 の再構築に失敗しました。"
                          f"今日はこのまま既存のループを流し続けます: {e}")
                else:
                    # ビルド中も started は動いていないはずなので、通常は
                    # 絶対に引っかからない。それでも引っかかるなら想定外の
                    # 事態（ビルドが異常に長い等）なので、アーカイブを
                    # 黙って失うより止めて知らせる。
                    assert_within_archive_window(started, datetime.now(timezone.utc))
                    proc.terminate(); proc.wait(timeout=30)
                    os.replace(next_path, LOOP_MP4)
                    proc = _spawn_ffmpeg(key)
                    last_built = now
    except (KeyboardInterrupt, ArchiveWindowExceeded) as e:
        print(f"! 配信を止めます: {e}")
    finally:
        proc.terminate()
        complete_broadcast(youtube)


if __name__ == "__main__":
    main()
