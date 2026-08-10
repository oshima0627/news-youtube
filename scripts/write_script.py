#!/usr/bin/env python3
"""レシピから台本を作って work/<id>/script.json に置く。

  python scripts/write_script.py recipes/<id>.json
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

from scripts.script_writer import write  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", type=Path)
    a = ap.parse_args()

    recipe = json.loads(a.recipe.read_text(encoding="utf-8"))
    script = write(recipe)

    workdir = ROOT / "work" / recipe["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "script.json").write_text(
        script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"✓ {script.title}")
    print(f"  {len(script.narration)}字 / {script.figure_label}: {script.figure_value}")


if __name__ == "__main__":
    main()
