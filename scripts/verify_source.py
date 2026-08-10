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
from dataclasses import asdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする
CANDIDATES = ROOT / "work" / "candidates.json"
RECIPES = ROOT / "recipes"

from scripts.evidence import Evidence, collect  # noqa: E402


def build_recipe(candidate: dict, ev: Evidence) -> dict:
    return {
        "id": candidate["id"],
        "headline": candidate["title"],
        "keyword": candidate["keyword"],
        "category": candidate["category"],
        "evidence": asdict(ev),
    }


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
        found = collect(c["keyword"])
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
