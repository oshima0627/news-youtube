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

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.cards_wide import (BODY_TOP, CARD_W, WIDE_SIZE,  # noqa: E402
                                render_headline, render_quote)
from scripts.draw import NAVY  # noqa: E402
from scripts.evidence import ground_excerpt  # noqa: E402

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


def render_frame(recipe: dict) -> Image.Image:
    """1題材ぶんの静止画。**写真枠は使わない。**

    50件ぶんの写真が work/ から消えており、取り直すと人物写真の
    取り違えリスクを新しい経路に持ち込む（CLAUDE.md）。

    引用カードは横中央に置く（写真枠 CARD_LEFT ではない）。CARD_LEFT は
    左に実写を置く前提の座標で、写真を使わないこの設計でそのまま使うと
    画面の左半分が紺色の空白になる。
    """
    ev = recipe["evidence"]
    base = Image.new("RGB", WIDE_SIZE, NAVY)
    base.paste(render_headline(recipe["headline"]), (0, 0))
    # ground_excerpt を通すことで、カードに出る文字列が逐語引用であることを担保する
    quote = ground_excerpt(ev["quote"], ev["quote"])
    base.paste(render_quote(quote, ev["context"]),
               ((WIDE_SIZE[0] - CARD_W) // 2, BODY_TOP))
    return base
