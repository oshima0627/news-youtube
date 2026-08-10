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
from scripts.narrate import TARGET_MAX, TARGET_MIN, wav_duration_seconds  # noqa: E402


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


def mp4_duration_seconds(path: Path) -> float:
    """ffprobe で mp4 の実尺（秒）を測る。

    voice.wav の尺を保証しても、それを ffmpeg で動画に焼いた後の
    最終成果物（mp4）がズレていれば無音動画を無自覚に投稿するのと
    同じ構造の失敗になる。中間生成物だけでなく最終成果物を必ず検証する
    ために ffprobe 呼び出しをこの関数に切り出し、単体テストできるように
    している（subprocess.run をモックすればよい）。
    """
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            f"ffprobeで尺を測れませんでした: {path}\n"
            f"returncode={proc.returncode}\nstderr:\n{proc.stderr}"
        )
    return float(proc.stdout.strip())


def verify_duration(mp4_path: Path) -> float:
    """mp4 の実尺を測り、56〜61秒の範囲外なら警告を出す。

    narrate.py の synthesize() と同じ理由（このチャンネルの収益化条件は
    「90日で3本以上の投稿」なので、尺が多少ずれた動画を出すより1本
    落とすほうが損失が大きい）で、例外にはせず警告のみ出してこのまま
    採用する。ただし気づけないと同じ問題を繰り返すため、必ず目立つ形で
    警告を出す。
    """
    duration = mp4_duration_seconds(mp4_path)
    if not (TARGET_MIN <= duration <= TARGET_MAX):
        print(f"! 警告: 完成したmp4の尺が{TARGET_MIN:.0f}〜{TARGET_MAX:.0f}秒の"
              f"範囲外です（{mp4_path}, 実尺{duration:.2f}秒）。"
              "narrate.pyの尺補正はwavに対してのみ効いており、動画合成後の"
              "ズレはここでしか検知できない。要確認。")
    return duration


def build(workdir: Path) -> Path:
    script = json.loads((workdir / "script.json").read_text(encoding="utf-8"))
    license_ = json.loads((workdir / "license.json").read_text(encoding="utf-8"))
    recipe = json.loads(
        (ROOT / "recipes" / f"{workdir.name}.json").read_text(encoding="utf-8"))
    # 数値カードの脚注に出す。どの一次資料から取った数字かを画面に残す
    source = recipe["evidence"]["context"]

    stage_path = workdir / "stage.png"
    compose_stage(workdir / "photo.jpg", script, source).save(stage_path)

    voice_path = workdir / "voice.wav"
    # voice.wav の実尺を測り、-t で出力尺を明示的に確定させる。
    # 実測では -shortest 任せだと（静止画ループを -r 30 にフレームレート
    # 変換する際の補間/丸めが原因とみられる）出力が音声より2秒以上長く
    # なるケースが確認された（wav 57.08秒 → mp4 59.4秒）。narrate.py の
    # 許容上限は61秒なので、-shortest のズレをそのまま許すとwavが
    # 58.6秒を超えた時点でmp4が61秒を超えてしまう。-t を明示することで
    # 出力尺をwavの実尺に固定し、この膨張を防ぐ。-shortest は -t と
    # 役割が重複するため外した。
    voice_duration = wav_duration_seconds(voice_path)

    out = workdir / "video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(stage_path),
        "-i", str(voice_path),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{voice_duration:.3f}",
        str(out),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpegの実行に失敗しました（workdir={workdir}, "
            f"stage={stage_path}, voice={voice_path}）:\n"
            f"{e.stderr}"
        ) from e

    mp4_duration = verify_duration(out)
    print(f"  尺: voice.wav {voice_duration:.2f}秒 → video.mp4 {mp4_duration:.2f}秒"
          f"（差 {mp4_duration - voice_duration:+.2f}秒）")
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
