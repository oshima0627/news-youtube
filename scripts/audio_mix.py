#!/usr/bin/env python3
"""ナレーションに BGM を敷く。**動画の音声はすべてここを通る。**

CLAUDE.md の「関門は1つにして、全経路がそれを通る形にする」に従い、
ffmpeg の音声入力を呼び出し側で組み立てない。`build_short.build()` と
`build_long.build()` は `mix()` が返した wav を渡すだけにする
（TikTok は `build_short.build()` を再利用しているので、この2つで全経路）。

## ここが守っているもの

**ナレーションが BGM に埋もれないこと。** これだけ。

判定は「聞いてみて良かった」ではなく、**ffmpeg が実際に書き出した音源を
ebur128 で測った値**で行う。計画値どうしを比べると差は定義上いつも
BGM_BELOW_VOICE_LU になり、フィルタの書き間違い・BGM の取り違え・
ゲインの掛け忘れが全部すり抜ける。

尺のズレ（`build_short.verify_duration`）は警告で通しているが、**分離比は
例外で止める**。尺が1秒ずれた動画は出せるが、ナレーションが聞こえない
動画は動画として成立しないため。
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.narrate import wav_duration_seconds  # noqa: E402

# 既定の BGM。自作曲を1曲だけ固定で使う。
#
# 隣の bgm-youtube リポジトリを直接参照しない。あちらの work/ は再生成・
# 削除されうるうえ、1本あたり340MBのwavを毎ビルド読む必要がない。
# 切り出したものをこのリポジトリ内に持つ。
BGM_PATH = ROOT / "assets" / "bgm" / "petrichor.m4a"

# BGM をナレーションの何 LU 下に置くか。
#
# 会話と背景音の分離は、放送のアクセシビリティ指針では概ね 10 LU 以上が
# 目安とされる。18 LU はそれより十分下に置く値で、「言われれば鳴っている
# と分かる」程度を狙っている。
BGM_BELOW_VOICE_LU = 18.0

# 実測した分離比がこれを割ったら書き出しを止める。
#
# 設計値（18 LU）より緩くしてあるのは、ebur128 の測定はゲート付きで
# 数値が素材によって数 LU 動くため。ここが 18 に張り付いていると、
# 設計どおり作った動画が測定のゆれだけで止まる。
MIN_SEPARATION_LU = 15.0

# 最終ミックスの目標ラウドネス。YouTube の基準値。
TARGET_LUFS = -14.0

# 最終ミックスの真のピーク上限（dBFS）。
TARGET_TRUE_PEAK_DBFS = -1.0

# ebur128 が無音に対して返す値。
SILENCE_LUFS = -70.0

# 中間ファイルの形式。32bit float にしてあるのは、合成の途中で
# クリップさせないため（最終段のリミッタで初めて頭を抑える）。
_INTERMEDIATE = ["-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le"]


class LoudnessUnreadable(RuntimeError):
    """音源を測れなかった。BGM のパス違い・切り出し失敗などで起きる。"""


class NarrationBuried(RuntimeError):
    """BGM が大きすぎてナレーションが埋もれる。"""


@dataclass(frozen=True)
class Loudness:
    integrated: float           # LUFS
    true_peak: float            # dBFS


@dataclass(frozen=True)
class MixReport:
    """`mix()` が実際に測った値。完了報告にそのまま出す。"""

    voice: Loudness             # ナレーション単体
    bed: Loudness               # ゲインを掛けた後の BGM（書き出したもの）
    final: Loudness             # 合成・正規化した後の最終ミックス
    separation_lu: float        # voice と bed の差。これが関門
    bgm_gain_db: float
    final_gain_db: float


# ---------------------------------------------------------------- 測る

def parse_loudness(stderr: str) -> Loudness:
    """ffmpeg の ebur128 サマリからラウドネスと真のピークを読む。

    **サマリ部だけを見る。** ebur128 は測定中もフレームごとに
    `t: 0.5 M: -70.0 S: -120.7 I: -70.0 LUFS ...` という行を出しており、
    stderr 全体を検索すると先頭（まだ何も測れていない t=0.5 秒時点）の
    -70.0 に一致してしまう。実測すると全音源が「無音」と判定された。
    """
    tail = stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s*(-?[\d.]+|-?inf)\s*LUFS", tail)
    peak = re.search(r"Peak:\s*(-?[\d.]+|-?inf)\s*dBFS", tail)
    if not integrated:
        raise LoudnessUnreadable(
            f"ebur128 の出力からラウドネスを読めませんでした:\n{stderr[-800:]}")

    value = float(integrated.group(1))
    if value <= SILENCE_LUFS:
        raise LoudnessUnreadable(
            f"測った音源が無音でした（I={value} LUFS）。"
            "BGM のパスか切り出しを確認してください")

    tp = float(peak.group(1)) if peak and peak.group(1) != "-inf" else -99.0
    return Loudness(integrated=value, true_peak=tp)


def measure(path: Path) -> Loudness:
    """音源を1本測る。"""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-filter:a", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise LoudnessUnreadable(
            f"ffmpeg で {path} を測れませんでした:\n{proc.stderr[-800:]}")
    return parse_loudness(proc.stderr)


# ---------------------------------------------------------------- 決める

def bgm_gain_db(voice: Loudness, bgm: Loudness) -> float:
    """BGM に掛けるゲイン。行き先は voice から BGM_BELOW_VOICE_LU 下。

    定数のゲインにしないのは、曲を差し替えたときに素材のラウドネスが
    そのまま音量差になってしまうため。静かな曲では聞こえず、大きい曲では
    ナレーションを潰す。行き先を実測から決めれば曲に依らない。
    """
    return (voice.integrated - BGM_BELOW_VOICE_LU) - bgm.integrated


def final_gain_db(mixed: Loudness) -> float:
    """最終ミックスを目標ラウドネスまで持ち上げるゲイン。"""
    return TARGET_LUFS - mixed.integrated


def assert_narration_audible(voice: Loudness, bed: Loudness) -> None:
    """実測した分離比が下限を割っていたら止める。"""
    separation = voice.integrated - bed.integrated
    if separation < MIN_SEPARATION_LU:
        raise NarrationBuried(
            f"BGM がナレーションの{separation:.1f} LU 下にしかありません"
            f"（下限{MIN_SEPARATION_LU:.0f} LU）。ナレーションが埋もれるので"
            "書き出しません。BGM_BELOW_VOICE_LU か素材を確認してください")


# ---------------------------------------------------------------- 焼く

def _run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{what}に失敗しました:\n{proc.stderr[-1500:]}")


def mix(voice_path: Path, out_path: Path, *,
        bgm_path: Path | None = None) -> MixReport:
    """ナレーションに BGM を敷いた wav を書き出す。

    尺は `voice_path` と同じ。BGM が短くても `-stream_loop` で最後まで鳴らす。
    """
    voice_path = Path(voice_path)
    out_path = Path(out_path)
    # 既定を引数のデフォルト値にしない。モジュール変数を差し替えても
    # 既定値は import 時に固定されてしまい、曲の差し替えが効かなくなる。
    bgm_path = Path(bgm_path if bgm_path is not None else BGM_PATH)
    if not bgm_path.exists():
        raise FileNotFoundError(
            f"BGM が見つかりません: {bgm_path}")

    duration = wav_duration_seconds(voice_path)
    work = out_path.parent

    # 1. 使う区間だけを素の音量で切り出す。ここを測れば、曲全体ではなく
    #    「実際に敷く区間」のラウドネスが分かる。
    bed_raw = work / "bgm_bed_raw.wav"
    _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(bgm_path),
          "-t", f"{duration:.3f}", *_INTERMEDIATE, str(bed_raw)],
         "BGM の切り出し")

    voice = measure(voice_path)
    gain = bgm_gain_db(voice, measure(bed_raw))

    # 2. ゲインを掛けて書き出し、**書き出したものを測る**。
    bed = work / "bgm_bed.wav"
    _run(["ffmpeg", "-y", "-i", str(bed_raw),
          "-filter:a", f"volume={gain:.2f}dB", *_INTERMEDIATE, str(bed)],
         "BGM の音量調整")
    bed_loudness = measure(bed)

    # 3. 関門。ここを通らなければ動画にしない。
    assert_narration_audible(voice, bed_loudness)

    # 4. 合成。amix は既定で入力数だけ音量を割る（normalize=1）ため
    #    normalize=0 にする。ここを既定のままにすると全体が 6 dB 下がる。
    mixed_raw = work / "mixed_raw.wav"
    _run(["ffmpeg", "-y", "-i", str(voice_path), "-i", str(bed),
          "-filter_complex",
          "[0:a]aresample=48000,aformat=channel_layouts=stereo[v];"
          "[1:a]aresample=48000,aformat=channel_layouts=stereo[b];"
          "[v][b]amix=inputs=2:normalize=0:duration=first[out]",
          "-map", "[out]", *_INTERMEDIATE, str(mixed_raw)],
         "ナレーションと BGM の合成")

    # 5. 目標ラウドネスまで持ち上げ、リミッタで真のピークを抑える。
    #    alimiter は既定で出力を自動レベル調整する（level=1）ので切る。
    #    切らないと、ここで決めた目標値ではなくリミッタの都合で音量が決まる。
    limit = 10 ** (TARGET_TRUE_PEAK_DBFS / 20)
    lift = final_gain_db(measure(mixed_raw))
    _run(["ffmpeg", "-y", "-i", str(mixed_raw),
          "-filter:a", f"volume={lift:.2f}dB,alimiter=limit={limit:.4f}:level=0",
          "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out_path)],
         "最終ミックスの書き出し")

    for stale in (bed_raw, bed, mixed_raw):
        stale.unlink(missing_ok=True)

    return MixReport(voice=voice, bed=bed_loudness, final=measure(out_path),
                     separation_lu=voice.integrated - bed_loudness.integrated,
                     bgm_gain_db=gain, final_gain_db=lift)
