#!/usr/bin/env python3
"""公開済みの動画を非公開に戻す。

  python scripts/unpublish.py <video_id>
  python scripts/unpublish.py --all-today

完全自動で公開しているので、事後に問題が判明したときの手段が要る。
これが唯一の保険なので、依存を増やさず単体で動くようにしてある。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    # 失敗の原因は stderr に出す。Windows 既定のロケール（cp932）のままだと
    # 日本語の原因メッセージだけが文字化けし、「原因がログにそのまま出る」
    # という各CLIの die()／中止メッセージの目的が損なわれる。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

PUBLISHED = ROOT / "state" / "published.json"

from scripts.upload_youtube import die, get_service, set_privacy  # noqa: E402

# publish_at は常に JST 運用（upload_youtube.py の --schedule も JST を渡す前提）。
# 実行環境のローカル日付（date.today()）で判定すると、サーバーのタイムゾーンが
# JST とズレたときに「静かに0件」になり事故を止められなくなる。かならず
# publish_at を日時としてパースし、JST の暦日で当日かどうかを判定する。
JST = timezone(timedelta(hours=9))


def _today_ids() -> list[str]:
    if not PUBLISHED.exists():
        die(f"{PUBLISHED} がありません。まだ何も公開していないか、"
            "state/published.json を作り直す必要があります")
    try:
        data = json.loads(PUBLISHED.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        die(f"{PUBLISHED} が壊れています（JSONとして読めません）: {e}")

    today_jst = datetime.now(JST).date()
    ids = []
    for key, v in data.get("videos", {}).items():
        publish_at = v.get("publish_at")
        if not publish_at:
            continue
        try:
            dt = datetime.fromisoformat(publish_at)
        except ValueError:
            # パース不能な値を黙って除外すると「対象がありません」に見えてしまい
            # 事故を止められない。動画IDを添えて必ず警告する
            vid = v.get("youtube_video_id") or key
            print(f"! publish_at をパースできません（対象から除外します）: "
                  f"{vid} publish_at={publish_at!r}")
            continue
        if dt.tzinfo is None:
            # タイムゾーン無しの値はこのパイプラインでは常にJSTとして書かれる想定
            dt = dt.replace(tzinfo=JST)
        if dt.astimezone(JST).date() == today_jst:
            vid = v.get("youtube_video_id")
            if not vid:
                # 動画IDが無いエントリは戻しようがないが、黙って落とすと
                # 「当日分は全部戻した」つもりで公開されたままの1本が残る。
                # publish_at のパース失敗と同じく必ず警告する。
                print(f"! youtube_video_id がありません（対象から除外します）。"
                      f"YouTube Studio で直接確認してください: "
                      f"{key} publish_at={publish_at}")
                continue
            ids.append(vid)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id", nargs="?")
    ap.add_argument("--all-today", action="store_true")
    a = ap.parse_args()

    ids = _today_ids() if a.all_today else ([a.video_id] if a.video_id else [])
    if not ids:
        print("対象がありません")
        return

    service = get_service()
    # これは完全自動公開に対する唯一の保険なので、1本目が失敗しても必ず
    # 残りを試す。失敗でループを抜けると2本目以降が public のまま残り、
    # 「戻したつもり」で事故が続く。set_privacy は動画が見つからないとき
    # die()（SystemExit）を投げるので、Exception だけでなくそれも捕まえる。
    failed: list[tuple[str, str]] = []
    for vid in ids:
        try:
            set_privacy(service, vid, "private")
        except (Exception, SystemExit) as e:      # noqa: BLE001
            failed.append((vid, str(e) or type(e).__name__))
            print(f"! 非公開に戻せませんでした（続行します）: "
                  f"https://www.youtube.com/watch?v={vid} {e}", file=sys.stderr)
            continue
        print(f"✓ 非公開に戻しました: https://www.youtube.com/watch?v={vid}")

    ok = len(ids) - len(failed)
    print(f"{len(ids)}件中{ok}件成功")
    if failed:
        print("✗ 以下は公開されたままの可能性があります。YouTube Studio で"
              "直接非公開にしてください:", file=sys.stderr)
        for vid, err in failed:
            print(f"  https://www.youtube.com/watch?v={vid}  ({err})",
                  file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
