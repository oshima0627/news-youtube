#!/usr/bin/env python3
"""静止画とナレーションから縦型ショートを組む。

  python scripts/build_short.py work/<id>

動きのある編集はしない。1枚の下地に音声を載せるだけにして、
差別化は数値カードの中身に寄せる。
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.cards import (HOLE_TOP, PHOTO_H, SHORT_SIZE, render_figure,  # noqa: E402
                           render_frame)


def _fill(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """アスペクト比を保ったまま size を覆うように拡大し、中央で切り取る。"""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    left = (resized.width - tw) // 2
    top = (resized.height - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def compose_stage(photo: Path, script: dict, source: str) -> Image.Image:
    """実写＋数値カード＋上下の帯を1枚に焼く。"""
    w, _ = SHORT_SIZE
    stage = Image.new("RGB", SHORT_SIZE, (16, 24, 43))

    with Image.open(photo) as im:
        stage.paste(_fill(im.convert("RGB"), (w, PHOTO_H)), (0, HOLE_TOP))

    figure = render_figure(script["figure_label"], script["figure_value"], source)
    stage.paste(figure, (0, HOLE_TOP + PHOTO_H))

    frame = render_frame(script["headline"], script["narration"])
    stage.paste(frame, (0, 0), frame)
    return stage


def build(workdir: Path) -> Path:
    script = json.loads((workdir / "script.json").read_text(encoding="utf-8"))
    license_ = json.loads((workdir / "license.json").read_text(encoding="utf-8"))
    recipe = json.loads(
        (ROOT / "recipes" / f"{workdir.name}.json").read_text(encoding="utf-8"))
    # 数値カードの脚注に出す。どの一次資料から取った数字かを画面に残す
    source = recipe["evidence"]["context"]

    stage_path = workdir / "stage.png"
    compose_stage(workdir / "photo.jpg", script, source).save(stage_path)

    out = workdir / "video.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(stage_path),
        "-i", str(workdir / "voice.wav"),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(out),
    ], check=True)
    print(f"  画像の出典: {license_['attribution'].splitlines()[0]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    a = ap.parse_args()
    out = build(a.workdir)
    print(f"✓ {out}")


if __name__ == "__main__":
    main()
