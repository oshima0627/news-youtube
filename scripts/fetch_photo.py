#!/usr/bin/env python3
"""画像を1枚落として work/<id>/ に置く。

  python scripts/fetch_photo.py work/<id> --speaker 片山さつき   # 自動で探す
  python scripts/fetch_photo.py work/<id> <画像URL>              # URLを指定する

日次実行（run_daily.py）は発言者から自動で決めるので、通常このCLIは要らない。
自動で選ばれた画像が題材に合わないときに、手で1枚差し替えるために使う。
run_daily.py は photo.jpg と license.json が既にあれば自動取得を行わないので、
ここで置いた画像は次の実行でも尊重される。
"""

from __future__ import annotations

import argparse
import json
import sys
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

from scripts.commons import credit, resolve  # noqa: E402
from scripts.photos import download  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    ap.add_argument("url", nargs="?",
                    help="画像URL。省略時は --speaker から自動で探す")
    ap.add_argument("--speaker", default="",
                    help="発言者名。ja.wikipedia の記事画像を使う")
    a = ap.parse_args()

    if a.url:
        url, note = a.url, ""
    else:
        info = resolve(a.speaker)
        if not info:
            print(f"✗ 使える画像が見つかりませんでした（{a.speaker or '発言者未指定'}）",
                  file=sys.stderr)
            sys.exit(1)
        url = info["url"]
        note = credit(info)
        who = "汎用画像" if info["is_fallback"] else f"{info['article']} の記事画像"
        print(f"- {who}（{info['license_name']} / "
              f"{info['width']}x{info['height']}）")

    rec = download(url, a.workdir / "photo.jpg", credit=note)
    (a.workdir / "license.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ {rec['file']}\n{rec['attribution']}")


if __name__ == "__main__":
    main()
