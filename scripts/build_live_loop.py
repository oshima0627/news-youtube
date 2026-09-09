#!/usr/bin/env python3
"""recipes/*.json から常時配信用のループ動画を1本組む。

  python scripts/build_live_loop.py --out work/live/loop.mp4

読み上げるのは 見出し / 一次資料の逐語引用 / 出典 の3つだけ。
モデルが書いた文字列は1文字も入らない。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.audio_mix import mix  # noqa: E402
from scripts.cards_wide import (BODY_TOP, CARD_W, WIDE_SIZE,  # noqa: E402
                                render_headline, render_quote)
from scripts.draw import NAVY  # noqa: E402
from scripts.evidence import ground_excerpt  # noqa: E402
from scripts.narrate import (SECONDS_PER_CHAR, synthesize,  # noqa: E402
                             wav_duration_seconds)

RECIPES_DIR = ROOT / "recipes"

# 推定尺に対して許容する上下の幅。ショートの 56〜61秒（±4%）より広いのは、
# ライブの1題材が引用文の長さでばらつくため。狭いと毎回警告が出て、
# 無音や合成失敗という本物の異常がその警告に埋もれる。
WINDOW_LOW = 0.70
WINDOW_HIGH = 1.40


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


def speech_window(text: str) -> tuple[float, float]:
    """`narrate.synthesize` に渡す尺の窓を文字数から決める。"""
    est = max(len(text) * SECONDS_PER_CHAR, 1.0)
    return est * WINDOW_LOW, est * WINDOW_HIGH


def build(out_path: Path, recipes: list[dict], *, workdir: Path | None = None) -> Path:
    """レシピを順に読み上げた16:9のループ用 mp4 を1本書き出す。

    配信側は再エンコードしない（`-c copy`）ので、ここで
    YouTube ライブに載る形（h264 + aac・2秒GOP）まで作り切る。
    """
    if not recipes:
        # 空のまま進めると frames[-1] が素の IndexError で落ち、
        # 「レシピが0件だった」という本当の原因が読み取れなくなる。
        raise ValueError("recipes が空です。1件以上のレシピが必要です。")

    out_path = Path(out_path)
    work = Path(workdir) if workdir else out_path.parent / "parts"
    work.mkdir(parents=True, exist_ok=True)

    frames, wavs = [], []
    for i, recipe in enumerate(recipes):
        text = narration_text(recipe)
        lo, hi = speech_window(text)
        raw = work / f"{i:03d}_voice.wav"
        synthesize(text, raw, target_min=lo, target_max=hi)
        mixed = work / f"{i:03d}_mixed.wav"
        mix(raw, mixed)                      # BGM の関門はここ1箇所だけ
        wavs.append(mixed)
        png = work / f"{i:03d}.png"
        render_frame(recipe).save(png)
        frames.append((png, wav_duration_seconds(mixed)))

    audio_list = work / "audio.txt"
    audio_list.write_text(
        "\n".join(f"file '{w.as_posix()}'" for w in wavs) + "\n", encoding="utf-8")
    frame_list = work / "frames.txt"
    lines = []
    for png, dur in frames:
        lines.append(f"file '{png.as_posix()}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{frames[-1][0].as_posix()}'")   # concat は最後を2度書く
    frame_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(frame_list),
        "-f", "concat", "-safe", "0", "-i", str(audio_list),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-g", "60", "-keyint_min", "60",     # 2秒GOP。YouTube ライブの要件
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-shortest", str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace")
    except subprocess.CalledProcessError as e:
        # build_long.py と同じ形にする。check=True だけに任せると、
        # 例外の repr に stderr が出ずに失敗原因が読み取れない。
        raise RuntimeError(
            f"ffmpegの実行に失敗しました（frames={frame_list}, audio={audio_list}）:\n"
            f"{e.stderr}") from e
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "work" / "live" / "loop.mp4")
    ap.add_argument("--exclude-category", action="append", default=[])
    args = ap.parse_args()
    recipes = select_recipes(RECIPES_DIR,
                             exclude_categories=frozenset(args.exclude_category))
    print(f"- レシピ {len(recipes)}件")
    path = build(args.out, recipes)
    print(f"✓ {path}")


if __name__ == "__main__":
    main()
