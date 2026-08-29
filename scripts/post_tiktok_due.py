#!/usr/bin/env python3
r"""枠の時刻が来た TikTok バリアントを投稿する。定時タスクの入口。

  python scripts/post_tiktok_due.py            # 枠が来た未投稿を投げる
  python scripts/post_tiktok_due.py --dry-run  # 投げずに対象だけ出す

TikTok の Direct Post API には予約投稿が無いので、07:30 / 18:30 に
「その時刻に実際に投げる」ことでしか YouTube の枠に揃えられない。
このスクリプトは **ANTHROPIC_API_KEY も VOICEVOX も要らない**（動画は
run_daily.py が先に作り終えている）ので、無人で回せる。

  schtasks /create /tn "tiktok-0725" /sc daily /st 07:25 ^
    /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"

失敗の分類は run_daily.py と同じ考え方にしてある。題材固有の失敗（動画が
無い・尺が足りない）はその1本を飛ばして残りを続け、環境ごとの失敗
（未審査・アカウント取り違え）はどの動画でも同じ理由で失敗するので中止する。
全件ぶん同じ失敗を繰り返した末に「0本」とだけ出ると原因に気づけない。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import tiktok, tiktok_queue                    # noqa: E402

JST = timezone(timedelta(hours=9))

# どの動画でも同じ理由で失敗する種類。1本目で出たらその場で止める。
FATAL = (tiktok.NotAudited, tiktok.AccountMismatch)


def run(state_dir: Path, now: datetime, post) -> int:
    """枠が来た未投稿を投げ、投稿できた本数を返す。

    `post(workdir) -> dict` は投稿1本ぶん。テストから差し替えられるように
    引数で受ける（本番は upload_tiktok.post に認証済みの api を束ねたもの）。
    """
    entries = tiktok_queue.due_entries(state_dir, now)
    if not entries:
        print("- 枠が来ている未投稿はありません")
        return 0

    posted = 0
    for entry in entries:
        workdir = entry["workdir"]
        try:
            result = post(workdir)
        except FATAL:
            # 認証・審査の状態はどの動画でも共通。残りを試しても同じ失敗を
            # 繰り返すだけなので、原因を上へ返して中止する。
            print(f"✗ 環境ごとの理由で投稿できません。残り"
                  f"{len(entries) - posted}本は試さず中止します: {workdir}",
                  file=sys.stderr)
            raise
        except tiktok.TikTokError as e:
            # 題材固有。キューに残るので、作り直せば次の枠で出せる。
            print(f"! この1本は投稿できませんでした（キューに残します）: "
                  f"{workdir}: {e}", file=sys.stderr)
            continue
        tiktok_queue.mark_posted(state_dir, workdir, result)
        posted += 1
        print(f"✓ 投稿しました: {workdir} "
              f"publish_id={result.get('publish_id')} "
              f"({result.get('privacy_level')})")
    return posted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="投稿せず、枠が来ている対象だけ表示する")
    ap.add_argument("--allow-self-only", action="store_true",
                    help="審査前でも SELF_ONLY で投稿する（経路の確認用）")
    a = ap.parse_args()

    state_dir = ROOT / "state"
    now = datetime.now(JST)

    if a.dry_run:
        for entry in tiktok_queue.due_entries(state_dir, now):
            print(f"- {entry['workdir']}  枠 {entry['due']}")
        return

    from scripts.tiktok_api import TikTokApi, TikTokAuthError
    from scripts.upload_tiktok import post as post_one

    try:
        api = TikTokApi.from_files(ROOT)
    except TikTokAuthError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)

    def post(workdir):
        return post_one(api, ROOT / workdir if not Path(workdir).is_absolute()
                        else Path(workdir),
                        allow_self_only=a.allow_self_only)

    try:
        count = run(state_dir, now, post)
    except tiktok.TikTokError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(getattr(e, "exit_code", 1))
    print(f"本日 {count} 本を TikTok に投稿しました")


if __name__ == "__main__":
    main()
