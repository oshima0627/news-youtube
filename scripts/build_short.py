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
if hasattr(sys.stderr, "reconfigure"):
    # 失敗の原因は stderr に出す。Windows 既定のロケール（cp932）のままだと
    # 日本語の原因メッセージだけが文字化けし、「原因がログにそのまま出る」
    # という各CLIの die()／中止メッセージの目的が損なわれる。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.draw import NAVY  # noqa: E402
from scripts.cards import (CARD_TOP, PHOTO_H, PHOTO_TOP, SHORT_SIZE,  # noqa: E402
                           TELOP_TOP, render_figure, render_headline,
                           render_quote, render_telop)
from scripts.narrate import (TARGET_MAX, TARGET_MIN, query_path,  # noqa: E402
                             segments_path, wav_duration_seconds)
from scripts.evidence import ground_excerpt  # noqa: E402
from scripts.telop import spans as telop_spans  # noqa: E402
from scripts.telop import stretch  # noqa: E402


# 縦方向の切り取り位置。0 が上端、0.5 が中央、1 が下端。
#
# 写真は人物のポートレート（縦長）が大半で、写真枠は横長（1080x659）なので、
# 縦に大きく切り落とすことになる。中央で切ると**頭の上が欠ける**
# （実測: 高市早苗・櫛渕万里・平口洋の公式ポートレートで額から上が欠けた）。
# 顔は写真の上寄りにあるので、切り取り位置も上に寄せる。
#
# 値は公式ポートレート5枚（片山さつき・高市早苗・櫛渕万里・平口洋・
# 打越さく良）を実際に描画して選んだ。0.15 では片山さつきの**顎**が
# 下端で切れ、0.30 では高市早苗・打越さく良の**髪の上**が切れる。
# 0.22 は5枚とも顔が枠内に収まる。
# 横長の写真では縦の余りがほとんど無いため、この値はほぼ効かない。
PHOTO_ANCHOR_Y = 0.22


def _fill(img: Image.Image, size: tuple[int, int],
          anchor_y: float = PHOTO_ANCHOR_Y) -> Image.Image:
    """アスペクト比を保ったまま size を覆うように拡大して切り取る。

    横方向は中央、縦方向は anchor_y の位置で切る。
    """
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    left = (resized.width - tw) // 2
    top = round((resized.height - th) * anchor_y)
    return resized.crop((left, top, left + tw, top + th))


def compose_base(photo: Path, script: dict, source: str,
                 figure: str = "", *, quote: str) -> Image.Image:
    """見出し＋実写＋根拠カードを焼いた土台。テロップの帯だけ空けておく。

    テロップは1本の動画で20枚前後に切り替わる。毎回ここからやり直すと
    写真の拡大縮小を20回繰り返すことになるので、変わらない部分を先に
    1枚作っておき、テロップの帯だけを差し替える。

    `quote`（一次資料の逐語引用）は必須にしてある。引用カードに出す文字列が
    一次資料に由来することを、**描く直前に**確かめるため（ground_excerpt）。
    省略できるようにしておくと、run_daily を通らない経路
    （write_script.py → build_short.py を手で叩く）が検証なしで描けてしまう。
    """
    w, _ = SHORT_SIZE
    stage = Image.new("RGB", SHORT_SIZE, NAVY)
    stage.paste(render_headline(script["headline"]), (0, 0))

    with Image.open(photo) as im:
        stage.paste(_fill(im.convert("RGB"), (w, PHOTO_H)), (0, PHOTO_TOP))

    card = (render_figure(script["figure_label"], script["figure_value"], source)
            if figure.strip()
            else render_quote(ground_excerpt(script["quote_excerpt"], quote),
                              source))
    stage.paste(card, (0, CARD_TOP))
    return stage


def compose_over(base: Image.Image, caption: str) -> Image.Image:
    """土台にテロップの帯を載せて1枚に焼く。"""
    stage = base.copy()
    stage.paste(render_telop(caption), (0, TELOP_TOP))
    return stage


def compose_stage(photo: Path, script: dict, source: str,
                  figure: str = "", *, quote: str) -> Image.Image:
    """実写＋根拠カード＋上下の帯を1枚に焼く。

    figure は一次資料が持っている実際の数値（`Evidence.figure`）。
    これが空でない系統（統計・公表）では数値カードを使い、空の系統（発言）では
    引用カードを使う。カードには必ず一次資料の出典キャプションが付くので、
    figure が空なのに数値カードを使うと、モデルが作った値に一次資料の出典が
    付いてしまう（設計方針「一次資料が取れなければ公開しない」の破れ）。

    字幕バンドに渡すのは script["subtitle"]。ナレーション全文（350〜400字）を
    渡すと4行＝60文字あまりしか描画されず、残り全部が毎ビルド切り捨て警告に
    なるうえ、画面には文の途中で切れた冒頭だけが60秒間出続ける。
    """
    base = compose_base(photo, script, source, figure, quote=quote)
    return compose_over(base, script["subtitle"])


def plan_frames(workdir: Path, script: dict,
                voice_duration: float) -> list[tuple[str, float, float]]:
    """下帯に出す文字列と、その表示区間を決める。

    ナレーションに同期したテロップを基本にする。静止画に固定の要点を
    60秒出し続けるのは「解説、教育的価値が最小限の画像スライドショー」
    そのもので、YouTube が収益化不可としている量産型コンテンツの
    例示に当てはまる。

    音声合成に使った audio_query（voice_query.json）が無い、または本文と
    音声の区切りが対応しないときは、従来どおり script["subtitle"] を
    1枚だけ出す。テロップが無い動画のほうが、作れない動画よりましなので。
    """
    query_file = query_path(workdir / "voice.wav")
    segments_file = segments_path(workdir / "voice.wav")
    if query_file.exists() and segments_file.exists():
        items = telop_spans(
            json.loads(segments_file.read_text(encoding="utf-8")),
            json.loads(query_file.read_text(encoding="utf-8")))
        if items:
            return stretch(items, voice_duration)
    else:
        print("! 音声の測定結果が無いためテロップを付けません"
              "（narrate.py で音声を作り直すと付きます）")
    return [(script["subtitle"], 0.0, voice_duration)]


def write_frames(workdir: Path, base: Image.Image,
                 frames: list[tuple[str, float, float]]) -> Path:
    """テロップごとの1枚絵を書き出し、ffmpeg の concat リストを返す。"""
    stage_dir = workdir / "frames"
    stage_dir.mkdir(parents=True, exist_ok=True)
    for stale in stage_dir.glob("*.png"):
        stale.unlink()              # 前回の残りを混ぜない

    lines: list[str] = []
    for i, (caption, start, end) in enumerate(frames):
        path = stage_dir / f"{i:03d}.png"
        compose_over(base, caption).save(path)
        lines.append(f"file '{path.name}'")
        lines.append(f"duration {end - start:.3f}")
    # concat デマルチプレクサは最後のファイルをもう一度並べないと、
    # 末尾の1枚が1コマだけになって最後のテロップが一瞬で消える
    lines.append(f"file '{len(frames) - 1:03d}.png'")

    concat_path = stage_dir / "frames.txt"
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 1枚目は stage.png としても残す（目視確認用）
    compose_over(base, frames[0][0]).save(workdir / "stage.png")
    return concat_path


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
    # 根拠カードの脚注に出す。どの一次資料から取った根拠かを画面に残す
    source = recipe["evidence"]["context"]
    figure = recipe["evidence"].get("figure") or ""

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

    base = compose_base(workdir / "photo.jpg", script, source, figure,
                        quote=recipe["evidence"].get("quote") or "")
    frames = plan_frames(workdir, script, voice_duration)
    concat_path = write_frames(workdir, base, frames)

    out = workdir / "video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
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
            f"frames={concat_path}, voice={voice_path}）:\n"
            f"{e.stderr}"
        ) from e

    mp4_duration = verify_duration(out)
    print(f"  尺: voice.wav {voice_duration:.2f}秒 → video.mp4 {mp4_duration:.2f}秒"
          f"（差 {mp4_duration - voice_duration:+.2f}秒）")
    print(f"  テロップ: {len(frames)}枚")
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
