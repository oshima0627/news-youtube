#!/usr/bin/env python3
"""台本のテロップが帯に収まるかを、**ビルドする前に**測る。

`build_short` はテロップが溢れても止まらず、`render_telop` が警告を1行出して
はみ出した行を切り捨てる。切り捨ては動画の中でしか見えないので、
音声合成と動画合成（実測で1本あたり数分）を払ったあとにしか気づけない。
ここは同じ割り付け・同じフォントで**幅と行数だけ**を測り、台本の段階で返す。

音声は要らない。`telop.spans` が音に合わせるのは各テロップの**表示時刻**で、
どの文字がひとまとまりになるか（＝帯に収まるか）は本文だけで決まるため。
秒数にダミーを入れて同じ経路（`_chunk` とマージ）を通している。

使い方:
    python scripts/check_telop.py work/scripts/koja_peace.json ...
    python scripts/check_telop.py work/scripts/*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cards import AVAIL, MARGIN, SHORT_SIZE, TELOP_MAX_LINES  # noqa: E402
from scripts.draw import normalize_numerals, pick_font, wrap  # noqa: E402
from scripts.telop import MERGE_UNDER, _chunk, split_segments  # noqa: E402

# render_telop のフォント縮小の手順と同じ値。ここがずれると、通ったのに
# 溢れる（または逆）になり、測っている意味が無くなる。
START_SIZE = 66
MIN_SIZE = 40
STEP = 4

# render_telop が本文の縁に付ける黒フチ。画面から出るかを測るなら、
# 文字の描画幅だけでなくこのぶんも足さないと 5px ぶん甘くなる。
STROKE = 5

# **画面から出る**のはここを越えたとき。`AVAIL`（＝左右に MARGIN を取った
# 幅）を越えただけでは切れない——`draw.wrap` は禁則処理のため、行頭に
# 置けない文字（「、」「。」など）を前の行に残して幅を意図的に超える。
# その超過を「はみ出し」として数えると、正常な出力を毎回落とすことになる。
CLIP_LIMIT = SHORT_SIZE[0] - MARGIN - STROKE


def captions(narration: str) -> list[str]:
    """本文から、画面に出るテロップの文字列を並べる（telop.spans と同じ経路）。"""
    merged: list[str] = []
    for segment in split_segments(narration):
        if merged and len(merged[-1]) < MERGE_UNDER:
            segment = merged.pop() + segment
        merged.extend(text for text, _ in _chunk(segment, 1.0))
    return [normalize_numerals(text) for text in merged]


def layout(d: ImageDraw.ImageDraw, text: str) -> tuple[int, list[str]]:
    """render_telop と同じ縮小手順で (フォントサイズ, 行) を返す。"""
    size = START_SIZE
    lines = wrap(d, text, pick_font(size), AVAIL)
    while len(lines) > TELOP_MAX_LINES and size > MIN_SIZE:
        size -= STEP
        lines = wrap(d, text, pick_font(size), AVAIL)
    return size, lines


def check(path: Path) -> int:
    """1本ぶんを測って、溢れたテロップの数を返す。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    narration = raw.get("narration") or ""
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    texts = captions(narration)
    over = 0
    widest = 0
    kinsoku = 0
    for text in texts:
        size, lines = layout(d, text)
        font = pick_font(size)
        for line in lines:
            box = d.textbbox((0, 0), line, font=font)
            width = box[2] - box[0]
            widest = max(widest, width)
            if MARGIN + width + STROKE > SHORT_SIZE[0]:
                over += 1
                print(f"  ! 画面の外に出ます（{MARGIN + width + STROKE}px > "
                      f"{SHORT_SIZE[0]}px, {size}pt）: {line}")
            elif width > AVAIL:
                kinsoku += 1
        if len(lines) > TELOP_MAX_LINES:
            over += 1
            print(f"  ! {len(lines)}行に割れて{len(lines) - TELOP_MAX_LINES}行"
                  f"切り捨てられます（{size}pt）: {text}")

    mark = "✓" if over == 0 else "✗"
    print(f"{mark} {path.name}: 本文{len(narration)}字 / テロップ{len(texts)}枚 / "
          f"最大描画幅 {widest}px（切れるのは {CLIP_LIMIT}px 超） / "
          f"はみ出し {over}枚 / 禁則で右余白に食い込む行 {kinsoku}")
    return over


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scripts", nargs="+", help="台本JSON")
    a = ap.parse_args()

    total = sum(check(Path(p)) for p in a.scripts)
    if total:
        sys.exit(f"✗ はみ出したテロップが {total} 枚あります。本文を短く区切ってください")
    print("✓ すべてのテロップが帯に収まります")


if __name__ == "__main__":
    main()
