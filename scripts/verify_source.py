#!/usr/bin/env python3
"""候補を一次資料に当てて、通ったものだけ recipes/<id>.json にする。

  python scripts/verify_source.py --want 2

candidates.json を上から順に当て、--want 件そろった時点で打ち切る。
そろわなければ少ないまま返す。**無理に埋めない。**
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
CANDIDATES = ROOT / "work" / "candidates.json"
RECIPES = ROOT / "recipes"

# build_recipe は run_daily.py と共有する。同じ形のレシピを2箇所で組み立てて
# いると、片方だけ形が変わったときに再現できないレシピが混ざる（evidence.py 参照）。
from scripts.evidence import (  # noqa: E402
    EvidenceSourcesUnavailable,
    build_recipe,
    collect,
)


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--want", type=int, default=2)
    a = ap.parse_args()

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    RECIPES.mkdir(parents=True, exist_ok=True)

    made: list[str] = []
    for c in candidates:
        if len(made) >= a.want:
            break
        try:
            found = collect(c["keyword"])
        except EvidenceSourcesUnavailable as e:
            # 一次資料の取得元そのものが疎通不能（環境不備）。「根拠が無かった」
            # （正常系）と混同して見送りを続けると、原因不明のまま採用0件に
            # なる。ここで即座に止めて原因を出す。
            die(f"一次資料の取得元に接続できません。中止します: {e}")
        if not found:
            print(f"- 見送り（根拠なし）: {c['title'][:32]}")
            continue
        recipe = build_recipe(c, found[0])
        path = RECIPES / f"{c['id']}.json"
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        made.append(c["id"])
        print(f"✓ 採用: {c['title'][:32]}  根拠={found[0].kind}")

    print(f"採用 {len(made)}/{a.want} 件")
    if len(made) < a.want:
        print("! 根拠の取れた題材が足りません。本数を減らして続行します")
    print(json.dumps(made, ensure_ascii=False))


if __name__ == "__main__":
    main()
