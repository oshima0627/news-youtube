#!/usr/bin/env python3
"""24時間のライブ配信を回す。ffmpeg は止めず、配信枠だけを差し替える。

  python scripts/run_live.py                          # 配信を始める（**公開**）
  python scripts/run_live.py --dry-run                # 何もせず、流す材料だけ確認する
  python scripts/run_live.py --stop                   # 配信中の枠を終了する
  python scripts/run_live.py --exclude-category election   # 投票日
"""

from __future__ import annotations

import argparse
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

from scripts.build_live_loop import RECIPES_DIR, build, select_recipes  # noqa: E402
from scripts.upload_youtube import get_service  # noqa: E402

STATE = ROOT / "state" / "live.json"

# アーカイブは12時間未満の配信でしか作られない（YouTube公式ヘルプ）。
# 超えた瞬間、その配信の再生時間は1分も4,000時間に入らない。
HARD_LIMIT = timedelta(hours=12)
# 30分のマージン。API の一時的な失敗で1回分を丸ごと失わないため。
# **このマージンを使い切るには、ローテーションの失敗を握って次のティックで
# やり直す必要がある**（main のローテーション部分の try/except）。例外が
# そのまま main を抜けると、マージンは1秒も使われずに配信が終わる。
ROTATE_AFTER = timedelta(hours=11, minutes=30)
# やり直しを諦める線。**マージンの中に必ず収まる位置に置く。**
# やり直しに終わりが無いと、API の失敗が30分続いたときティックが
# `HARD_LIMIT` を越えてから assert_within_archive_window で止まる——
# つまり **12時間を跨いだあとで枠を閉じる**ことになり、アーカイブは
# 作られず11時間半が丸ごと0分になる。この線を越えたらやり直しをやめ、
# まだ窓の中にいるうちに枠を確定させてデーモンを止める。
ROTATION_GIVE_UP_AFTER = HARD_LIMIT - timedelta(minutes=5)

# ffmpeg の再起動の上限（この窓の中でこの回数を超えたら止めて通知する）。
# loop.mp4 が壊れていると ffmpeg は即座に落ち、上限が無いと11.5時間ぶん
# 60秒ごとに再起動を繰り返す。配信枠は live のまま、映像は一度も届かない
# ——**中身の無いアーカイブが1本できて、異常はどこにも出ない。**
FFMPEG_RESTART_WINDOW = timedelta(hours=1)
FFMPEG_RESTART_LIMIT = 10

# ingest が YouTube 側に登録されるまでの待ち。transition(live) は
# バインドしたストリームが active でないと errorStreamInactive で失敗する。
STREAM_ACTIVE_TIMEOUT = 300.0
STREAM_POLL_SECONDS = 5.0


class ArchiveWindowExceeded(RuntimeError):
    """12時間に達した。この配信のアーカイブはもう作られない。"""


class FfmpegRestartLimit(RuntimeError):
    """ffmpeg の再起動が上限を超えた。映像が届いていない可能性が高い。"""


class StreamNotActive(RuntimeError):
    """ingest が active にならない。この状態で live にはできない。"""


class RotationGaveUp(RuntimeError):
    """枠の切り替えが繰り返し失敗し、12時間の壁の手前で諦めた。"""


def should_rotate(started_at: datetime, now: datetime) -> bool:
    return now - started_at >= ROTATE_AFTER


def should_give_up_rotation(started_at: datetime, now: datetime) -> bool:
    """切り替えのやり直しをやめて、いまの枠を確定させるか。

    `ROTATE_AFTER` と `HARD_LIMIT` の間の30分は、API の一時的な失敗を
    次のティックでやり直すためのマージン。**ただしやり直しには終わりが
    要る。** 失敗が続いたまま `HARD_LIMIT` に達すると、そのとき初めて
    assert_within_archive_window が投げるが、その時点で配信はすでに
    12時間を跨いでいて、閉じてもアーカイブは作られない
    （11時間半ぶんが丸ごと0分）。ここで先に諦めれば、窓の中にいるうちに
    枠が確定してアーカイブが残る。
    """
    return now - started_at >= ROTATION_GIVE_UP_AFTER


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


def record_restart(restarts: list[datetime], now: datetime) -> list[datetime]:
    """ffmpeg の再起動を1件記録し、窓の外に出た記録を落として返す。"""
    return [t for t in restarts if now - t < FFMPEG_RESTART_WINDOW] + [now]


def too_many_restarts(restarts: list[datetime]) -> bool:
    return len(restarts) > FFMPEG_RESTART_LIMIT


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


def wait_for_stream_active(youtube, stream_id: str, *,
                           timeout_seconds: float = STREAM_ACTIVE_TIMEOUT,
                           poll_seconds: float = STREAM_POLL_SECONDS,
                           sleep=time.sleep, clock=time.monotonic) -> None:
    """ingest が active になるまで待つ。ならなければ `StreamNotActive`。

    `transition(live)` はバインドしたストリームが active でないと
    errorStreamInactive で失敗する。ffmpeg を起こしてから YouTube 側に
    登録されるまで数秒〜数十秒かかるので、**初回は待たずに transition すると
    まず失敗する**。
    """
    deadline = clock() + timeout_seconds
    while True:
        items = youtube.liveStreams().list(
            part="status", id=stream_id).execute().get("items", [])
        status = (items[0].get("status", {}).get("streamStatus")
                  if items else None)
        if status == "active":
            return
        if clock() >= deadline:
            raise StreamNotActive(
                f"ストリーム {stream_id} が {timeout_seconds:.0f} 秒たっても "
                f"active になりません（いまの状態: {status}）。"
                "ffmpeg が RTMP に届いているか確認してください。")
        sleep(poll_seconds)


def start_broadcast(youtube, stream_id: str, title: str, *,
                    now: datetime, state_path: Path = STATE) -> str:
    """配信枠を1つ作り、ストリームに結び付けて live にする。

    **関門はこの関数の中にある。** 呼び出し側に移さないこと。
    キューのフィルタ側にだけ置いた結果、直接叩く経路が素通りした前例がある
    （known-issues 2・3・8番、`upload_tiktok.post()` と同型）。

    ingest が active になるのを待つのもこの中で行う。呼び出し側に置くと、
    直接叩く経路が errorStreamInactive で落ちる。
    """
    state = _read_state(state_path)
    if state.get("broadcast_id") and state.get("live"):
        raise AlreadyStreaming(
            f"配信中の枠があります: {state['broadcast_id']}"
            f"（開始 {state.get('started_at')}）")

    # 定数はここで読む（既定引数に束ねない）。束ねると import 時に固定され、
    # テストから待ち時間を縮められない。
    wait_for_stream_active(youtube, stream_id,
                           timeout_seconds=STREAM_ACTIVE_TIMEOUT,
                           poll_seconds=STREAM_POLL_SECONDS)

    body = {
        # naive な datetime をそのまま Z で刻むと、ローカル時刻を UTC と
        # 偽って送ることになる。astimezone で必ず UTC に直してから刻む。
        "snippet": {"title": title,
                    "scheduledStartTime": now.astimezone(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ")},
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


def _stop_ffmpeg(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=30)


def rebuild_loop(next_path: Path, exclude_categories: frozenset[str]) -> Path:
    """新しい loop.mp4 を**別名で**1本作る。

    `exclude_categories` は起動時に渡されたものをそのまま使う。ここに
    渡し忘れると、投票日に除外つきで作ったループが最初のローテーションで
    除外なしのループに差し替わる（公職選挙法129条）。

    シャッフルの種になる `day` は **UTC の日付**を渡す。再構築の引き金
    （`should_rebuild`）が UTC の日付で判定しているので、`build` の既定の
    `date.today()`（ローカル日付）に任せると両者がずれる。JST では
    20:00 UTC の再構築が翌ローカル日付の種を引き、その約11時間半後の
    07:30 UTC の再構築が同じローカル日付の種を引くため、続けて2本
    まったく同じ並びのループが流れる（量産型に見せないためのシャッフルが
    半分死ぬ）。
    """
    return build(next_path, select_recipes(
        RECIPES_DIR, exclude_categories=exclude_categories),
        day=datetime.now(timezone.utc).date())


def _title(started: datetime) -> str:
    return f"ニュースラジオ {started:%Y-%m-%d %H:%M} UTC"


def _run_forever(exclude_categories: frozenset[str]) -> None:
    youtube = get_service()
    stream_id, key = ensure_stream(youtube)
    proc = _spawn_ffmpeg(key)
    restarts: list[datetime] = []
    try:
        started = datetime.now(timezone.utc)
        last_built = started
        broadcast_id = start_broadcast(youtube, stream_id, _title(started), now=started)
        print(f"✓ 配信を開始しました: {broadcast_id}"
              f"（{started:%Y-%m-%d %H:%M} UTC 開始・公開）")
    except BaseException:
        # ここで落ちると ffmpeg だけが固定の RTMP キーに流し続ける。
        # **配信枠には触らない。** complete_broadcast は共有の状態ファイルを
        # 読むので、二重起動で弾かれた2つ目のプロセスがこれを呼ぶと、
        # 動いている1本目の配信を終わらせてしまう。
        proc.terminate()
        raise
    try:
        while True:
            time.sleep(60)
            now = datetime.now(timezone.utc)
            if proc.poll() is not None:                 # ffmpeg が落ちた
                restarts = record_restart(restarts, now)
                if too_many_restarts(restarts):
                    raise FfmpegRestartLimit(
                        f"ffmpeg の再起動が {FFMPEG_RESTART_WINDOW} で "
                        f"{len(restarts)} 回に達しました。loop.mp4 が壊れている"
                        "可能性があります。配信を止めます。")
                print(f"! ffmpeg が落ちたので再起動します"
                      f"（直近 {FFMPEG_RESTART_WINDOW} で {len(restarts)} 回目）")
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
                #
                # API の一時的な失敗でデーモンごと終わらせない。`started` を
                # 更新しないまま抜けるので、次のティック（60秒後）が
                # should_rotate で True になり、そのままやり直す。
                # 30分のマージンはこのやり直しのためにある。
                #
                # complete だけ成功して start に失敗した場合、やり直しで
                # 2本目の枠が作られ、1本目は created のまま残る。**これは
                # 承知のうえで取る側。** 宙に浮いた枠は何も費やさないが、
                # 11時間のアーカイブを落とすと丸ごと0時間になる。
                try:
                    complete_broadcast(youtube)
                    new_started = datetime.now(timezone.utc)
                    broadcast_id = start_broadcast(
                        youtube, stream_id, _title(new_started), now=new_started)
                    started = new_started
                    rotated = True
                    print(f"✓ 配信枠を切り替えました: {broadcast_id}"
                          f"（{new_started:%Y-%m-%d %H:%M} UTC 開始）")
                except Exception as e:
                    # やり直しには終わりを付ける。ここで諦めずに
                    # HARD_LIMIT まで粘ると、止まるころには12時間を
                    # 跨いだあとで、アーカイブは1本も残らない。
                    if should_give_up_rotation(started, now):
                        raise RotationGaveUp(
                            f"配信枠の切り替えが開始から {now - started} "
                            f"経っても成功しません（最後の失敗: {e}）。"
                            f"12時間を越えるとアーカイブが作られないので、"
                            f"いまの枠を確定させて配信を止めます。") from e
                    print(f"! 配信枠の切り替えに失敗しました。"
                          f"次のティックでやり直します: {e}")
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
                try:
                    rebuild_loop(next_path, exclude_categories)
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
                    # ここで止め切れなかったら例外で抜ける。生き残った ffmpeg を
                    # 放って2本目を起こすと、同じキーに2本流し込むことになる。
                    _stop_ffmpeg(proc)
                    try:
                        os.replace(next_path, LOOP_MP4)
                    except OSError as e:
                        # 差し替えに失敗しても LOOP_MP4 は古いままなので、
                        # そのまま起こし直せば配信は続く（last_built を
                        # 更新していないので次のローテーションで再挑戦する）。
                        print(f"! loop.mp4 の差し替えに失敗しました。"
                              f"既存のループを流し続けます: {e}")
                    else:
                        last_built = now
                        print(f"✓ loop.mp4 を差し替えました（{now:%Y-%m-%d} 版）")
                    proc = _spawn_ffmpeg(key)
    except (KeyboardInterrupt, ArchiveWindowExceeded) as e:
        print(f"! 配信を止めます: {e}")
    except (FfmpegRestartLimit, RotationGaveUp) as e:
        print(f"✗ {e}")
    finally:
        proc.terminate()
        complete_broadcast(youtube)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stop", action="store_true",
                    help="配信中の枠を終了してアーカイブを確定させる。"
                         "落ちたあとの後始末はこれで行う（state/live.json を手で編集しない）")
    ap.add_argument("--dry-run", action="store_true",
                    help="配信枠も ffmpeg も作らず、流す材料と除外指定だけ確認する")
    ap.add_argument("--exclude-category", action="append", default=[],
                    help="除外するカテゴリ（投票日は election）。繰り返し指定できる。"
                         "プロセスが生きている間ずっと効く")
    args = ap.parse_args(argv)
    exclude = frozenset(args.exclude_category)

    if args.stop:
        # 落ちたあと state/live.json には live: true が残り、次の起動は
        # AlreadyStreaming で止まる。手で state を書き換えるのは設計と
        # CLAUDE.md の両方が禁じているので、正規の出口をここに置く。
        broadcast_id = complete_broadcast(get_service())
        print(f"✓ 配信枠を終了しました: {broadcast_id}" if broadcast_id
              else "- 配信中の枠はありません")
        return

    if not LOOP_MP4.exists():
        raise SystemExit(
            f"✗ {LOOP_MP4} がありません。先に "
            f"python scripts/build_live_loop.py を実行してください。")

    if args.dry_run:
        # 除外指定の綴りはここで確かめられる（一致0件なら例外で止まる）。
        recipes = select_recipes(RECIPES_DIR, exclude_categories=exclude)
        print(f"- レシピ {len(recipes)}件")
        print(f"- 除外カテゴリ: {sorted(exclude) if exclude else 'なし'}")
        print(f"- ループ動画: {LOOP_MP4}")
        print("- --dry-run のため、配信枠の作成も ffmpeg の起動も行いません"
              "（**公開されません**）")
        return

    print("- 公開ライブ配信を開始します（privacyStatus: public）")
    _run_forever(exclude)


if __name__ == "__main__":
    main()
