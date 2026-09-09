#!/usr/bin/env python3
"""recipes/*.json から常時配信用のループ動画を1本組む。

  python scripts/build_live_loop.py --out work/live/loop.mp4

読み上げるのは 見出し / 一次資料の逐語引用 / 出典 の3つだけ。
モデルが書いた文字列は1文字も入らない。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

RECIPES_DIR = ROOT / "recipes"


def select_recipes(recipes_dir: Path, *,
                   exclude_categories: frozenset[str] = frozenset()) -> list[dict]:
    """ループに載せるレシピを id 昇順で返す。

    `exclude_categories` は投票日に選挙関連を外すためにある
    （公職選挙法129条。動き続ける配信は継続的な公開行為にあたる）。
    """
    out = []
    for path in sorted(Path(recipes_dir).glob("*.json")):
        recipe = json.loads(path.read_text(encoding="utf-8"))
        if recipe.get("category") in exclude_categories:
            continue
        out.append(recipe)
    return sorted(out, key=lambda r: r["id"])


def narration_text(recipe: dict) -> str:
    """読み上げる文字列。**見出し・逐語引用・出典の連結だけ。**

    ここに定型の地の文（「続いてのニュースです」等）を足さないこと。
    足した瞬間、一次資料に無い文字列が出典キャプション付きで読み上げられ、
    「一次資料が取れなければ公開しない」がこの経路だけ破れる。
    """
    ev = recipe["evidence"]
    return "\n".join([recipe["headline"], ev["quote"], ev["context"]])
