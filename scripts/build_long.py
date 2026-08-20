#!/usr/bin/env python3
"""静止画とナレーションから長尺（16:9・約4分）を組む。

  python scripts/build_long.py work/<id>

`work/<id>/long.json`（run_long.py が書く）に並んだパートを順に描画し、
音声を連結して1本の mp4 にする。パートは

  導入 → ①題材 → ②題材 → ③題材 → 結び

の並びで、題材のパートだけが一次資料（逐語引用）に紐づく。
導入と結びは目次面を出す（一次資料の出典キャプションが付く要素を置かない）。

動きのある編集はしないのはショート（build_short.py）と同じ。差別化は
根拠カードの中身に寄せる。
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

from scripts.build_short import _fill, mp4_duration_seconds  # noqa: E402,F401
from scripts.cards_wide import (BODY_H, BODY_TOP, CARD_LEFT,  # noqa: E402
                                PHOTO_LEFT, PHOTO_W, TELOP_TOP, WIDE_SIZE,
                                render_contents, render_headline, render_quote,
                                render_telop)
from scripts.draw import NAVY  # noqa: E402
from scripts.evidence import ground_excerpt  # noqa: E402
from scripts.narrate import (query_path, segments_path,  # noqa: E402
                             wav_duration_seconds)
from scripts.telop import spans as telop_spans  # noqa: E402
from scripts.telop import stretch  # noqa: E402

# ── 尺の窓 ───────────────────────────────────────────────────
#
# 題材のパートは script_writer.SEGMENT_MIN/MAX_CHARS（410〜450字）を
# 素直に読むと 70.1〜77.0秒になる（0.171秒/字）。窓の中央を74秒に置くと
# speedScale は 0.95〜1.04 で収まり、可動域（0.85〜1.35）に張り付かない。
# 字数指定との対応は tests/test_script_writer.py が縛っている。
SEGMENT_TARGET_MIN = 68.0
SEGMENT_TARGET_MAX = 80.0

# 導入・結びは定型文なので字数がほぼ動かない。窓は「定型文を書き換えた
# ときに気づくための箱」として広めに取ってある。
#
# **下限は CHAPTER_MIN_SECONDS（10秒）を下回らせない。** 章が1つでも
# 10秒未満だと YouTube は章立てごと無効にする。実測では結びが7.9秒で、
# 章が5つあっても1本も出ない状態だった。
INTRO_TARGET_MIN = 12.0
INTRO_TARGET_MAX = 26.0
OUTRO_TARGET_MIN = 10.5
OUTRO_TARGET_MAX = 16.0

# 音声の合計と mp4 の実尺のずれをどこまで許すか（秒）。
# ショートのような固定の窓（56〜61秒）は長尺には無いので、代わりに
# 「入力した音声と出来上がった動画の長さが合っているか」を見る。
DURATION_TOLERANCE = 2.0

# YouTube の章として認識される条件（各章10秒以上）。
CHAPTER_MIN_SECONDS = 10.0

FPS = 30


def compose_segment(photo: Path, script: dict, source: str, number: int,
                    *, quote: str) -> Image.Image:
    """題材のパートの土台。見出し＋実写＋引用カード。テロップの帯は空ける。

    `quote`（一次資料の逐語引用）は**キーワード必須引数**にしてある。
    引用カードに出す文字列が一次資料に由来することを、描く直前に
    確かめるため（ground_excerpt）。省略できるようにすると、この関数を
    通らない経路が検証なしで描けてしまい、ショートで塞いだ穴
    （docs/known-issues.md 2番）が長尺側にもう一度空く。
    """
    stage = Image.new("RGB", WIDE_SIZE, NAVY)
    stage.paste(render_headline(script["headline"], number), (0, 0))

    with Image.open(photo) as im:
        stage.paste(_fill(im.convert("RGB"), (PHOTO_W, BODY_H)),
                    (PHOTO_LEFT, BODY_TOP))

    card = render_quote(ground_excerpt(script["quote_excerpt"], quote), source)
    stage.paste(card, (CARD_LEFT, BODY_TOP))
    return stage


def compose_bumper(headlines: list[str], headline: str) -> Image.Image:
    """導入・結びの土台。目次面だけを出す。

    このパートは特定の一次資料に紐づかないので、実写も引用カードも置かない
    （出典キャプションが付いた要素を、裏づけの無いナレーションと一緒に
    出さないため）。
    """
    stage = Image.new("RGB", WIDE_SIZE, NAVY)
    stage.paste(render_headline(headline, 0), (0, 0))
    stage.paste(render_contents(headlines), (0, BODY_TOP))
    return stage


def compose_over(base: Image.Image, caption: str) -> Image.Image:
    """土台にテロップの帯を載せて1枚に焼く。"""
    stage = base.copy()
    stage.paste(render_telop(caption), (0, TELOP_TOP))
    return stage


def part_frames(wav: Path, fallback: str) -> list[tuple[str, float, float]] | None:
    """1パートぶんのテロップ割り付け。作れなければ None。

    ショート（build_short.plan_frames）と同じく、音声合成に使った
    audio_query から「どの句が何秒目に読まれるか」を出す。
    """
    query_file = query_path(wav)
    segments_file = segments_path(wav)
    if not (query_file.exists() and segments_file.exists()):
        print(f"! {wav.name} の測定結果が無いためこのパートは静止字幕になります")
        return None
    items = telop_spans(json.loads(segments_file.read_text(encoding="utf-8")),
                        json.loads(query_file.read_text(encoding="utf-8")))
    if not items:
        return None
    return stretch(items, wav_duration_seconds(wav))


def join_frames(parts: list[list[tuple[str, float, float]] | None],
                durations: list[float],
                fallbacks: list[str] | None = None
                ) -> list[tuple[str, float, float]]:
    """パートごとの割り付けを、通しの時刻に直して1本に並べる。

    各パートの割り付けは「そのパートの先頭を0秒」として作られている。
    ずらし忘れると2章目以降が動画の冒頭に重なって出て、残りは1枚も出ない。

    割り付けを作れなかったパート（None）は、そのパートの尺いっぱいの
    静止字幕1枚で埋める。埋めないとそのパートだけ画面が飛ぶ。
    """
    out: list[tuple[str, float, float]] = []
    at = 0.0
    for items, duration in zip(fill_missing(parts, durations, fallbacks),
                               durations):
        out.extend((text, at + start, at + end) for text, start, end in items)
        at += duration
    return out


def fill_missing(parts: list[list[tuple[str, float, float]] | None],
                 durations: list[float],
                 fallbacks: list[str] | None = None
                 ) -> list[list[tuple[str, float, float]]]:
    """割り付けを作れなかったパートを、尺いっぱいの静止字幕1枚で埋める。

    描画（_write_frames）と通しの時刻の計算（join_frames）が別々に埋め方を
    決めると、片方だけ直したときに枚数と時刻が食い違う。埋め方はここだけに置く。
    """
    fallbacks = fallbacks or [""] * len(parts)
    return [items if items else [(fallback, 0.0, duration)]
            for items, duration, fallback in zip(parts, durations, fallbacks)]


def chapters(titles: list[str], durations: list[float]) -> list[str]:
    """`description` の先頭に置く章の一覧。

    YouTube が章として認識する条件は「最初が 00:00」「3つ以上」
    「各章10秒以上」。パートの実尺が分かっているのでそのまま書ける。
    """
    lines: list[str] = []
    at = 0.0
    for title, duration in zip(titles, durations):
        lines.append(f"{int(at) // 60:02d}:{int(at) % 60:02d} {title}")
        if duration < CHAPTER_MIN_SECONDS:
            print(f"! 「{title}」が{duration:.1f}秒しかありません"
                  f"（YouTubeの章は各10秒以上。章立てが無効になります）")
        at += duration
    return lines


def verify_duration(mp4_path: Path, expected: float) -> float:
    """mp4 の実尺が、入力した音声の合計とほぼ一致するか確かめる。

    ショートは 56〜61秒という固定の窓で見ているが（build_short）、長尺に
    固定の窓は無い。代わりに「入れた音声と出来上がった動画の長さが合って
    いるか」を見る。ずれていれば音声の取りこぼしか無音の付加が起きている。

    例外にはせず警告に留めるのはショートと同じ理由（1本落とすほうが痛い）。
    """
    duration = mp4_duration_seconds(mp4_path)
    if abs(duration - expected) > DURATION_TOLERANCE:
        print(f"! 警告: 完成したmp4の尺が音声の合計と{duration - expected:+.2f}秒"
              f"ずれています（{mp4_path}, 実尺{duration:.2f}秒 / "
              f"音声{expected:.2f}秒）。音声の取りこぼしか無音の付加が"
              "起きている可能性があります。要確認。")
    return duration


def _concat_audio(workdir: Path, wavs: list[Path]) -> Path:
    """パートごとの wav を1本に連結する。"""
    listing = workdir / "audio.txt"
    listing.write_text(
        "\n".join(f"file '{w.name}'" for w in wavs) + "\n", encoding="utf-8")
    out = workdir / "voice.wav"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
           "-i", str(listing), "-c:a", "pcm_s16le", str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"音声の連結に失敗しました（{listing}）:\n{e.stderr}") from e
    return out


def _write_frames(workdir: Path, bases: list[Image.Image],
                  per_part: list[list[tuple[str, float, float]]]) -> Path:
    """パートごとの土台にテロップを載せて書き出し、concat リストを返す。"""
    stage_dir = workdir / "frames"
    stage_dir.mkdir(parents=True, exist_ok=True)
    for stale in stage_dir.glob("*.png"):
        stale.unlink()              # 前回の残りを混ぜない

    lines: list[str] = []
    i = 0
    for base, items in zip(bases, per_part):
        for caption, start, end in items:
            path = stage_dir / f"{i:04d}.png"
            compose_over(base, caption).save(path)
            lines.append(f"file '{path.name}'")
            lines.append(f"duration {end - start:.3f}")
            i += 1
    # concat デマルチプレクサは最後のファイルをもう一度並べないと、
    # 末尾の1枚が1コマだけになって最後のテロップが一瞬で消える
    lines.append(f"file '{i - 1:04d}.png'")

    concat_path = stage_dir / "frames.txt"
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    compose_over(bases[0], per_part[0][0][0]).save(workdir / "stage.png")
    return concat_path


def build(workdir: Path) -> Path:
    """long.json のパートを順に組み、1本の mp4 にする。"""
    manifest = json.loads((workdir / "long.json").read_text(encoding="utf-8"))
    parts = manifest["parts"]
    headlines = [p["headline"] for p in parts if p["kind"] == "segment"]

    bases: list[Image.Image] = []
    per_part: list[list[tuple[str, float, float]]] = []
    wavs: list[Path] = []
    durations: list[float] = []

    number = 0
    for part in parts:
        wav = workdir / part["wav"]
        wavs.append(wav)
        durations.append(wav_duration_seconds(wav))

        if part["kind"] == "segment":
            number += 1
            bases.append(compose_segment(
                workdir / part["photo"], part, part["source"], number,
                quote=part["quote"]))
        else:
            bases.append(compose_bumper(headlines, part["headline"]))

        items = part_frames(wav, part["subtitle"])
        per_part.append(items)

    fallbacks = [p["subtitle"] for p in parts]
    filled = fill_missing(per_part, durations, fallbacks)

    voice = _concat_audio(workdir, wavs)
    total = wav_duration_seconds(voice)

    # 映像の総尺（テロップの終わり）と音声の合計が食い違っていれば、
    # どこかのパートで割り付けと wav がずれている。焼く前に気づけるよう見る。
    timeline = join_frames(per_part, durations, fallbacks)[-1][2]
    if abs(timeline - total) > DURATION_TOLERANCE:
        print(f"! 警告: テロップの総尺{timeline:.2f}秒と音声の合計{total:.2f}秒が"
              f"{timeline - total:+.2f}秒ずれています。要確認。")

    concat_path = _write_frames(workdir, bases, filled)

    out = workdir / "video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-i", str(voice),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
        "-t", f"{total:.3f}",
        str(out),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpegの実行に失敗しました（workdir={workdir}, "
            f"frames={concat_path}, voice={voice}）:\n{e.stderr}") from e

    mp4_duration = verify_duration(out, total)
    print(f"  尺: 音声{total:.2f}秒 → video.mp4 {mp4_duration:.2f}秒"
          f"（差 {mp4_duration - total:+.2f}秒）")
    print(f"  パート: {len(parts)}  テロップ: {sum(len(f) for f in filled)}枚")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    a = ap.parse_args()
    out = build(a.workdir)
    print(f"✓ {out}")


if __name__ == "__main__":
    main()
