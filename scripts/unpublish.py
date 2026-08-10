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
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

PUBLISHED = ROOT / "state" / "published.json"

from scripts.upload_youtube import die, get_service, set_privacy  # noqa: E402


def _today_ids() -> list[str]:
    if not PUBLISHED.exists():
        die(f"{PUBLISHED} がありません。まだ何も公開していないか、"
            "state/published.json を作り直す必要があります")
    try:
        data = json.loads(PUBLISHED.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        die(f"{PUBLISHED} が壊れています（JSONとして読めません）: {e}")
    today = date.today().isoformat()
    return [v["youtube_video_id"] for v in data.get("videos", {}).values()
            if (v.get("publish_at") or "").startswith(today)]


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
    for vid in ids:
        set_privacy(service, vid, "private")
        print(f"✓ 非公開に戻しました: https://www.youtube.com/watch?v={vid}")


if __name__ == "__main__":
    main()
