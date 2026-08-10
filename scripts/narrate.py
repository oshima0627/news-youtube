#!/usr/bin/env python3
"""VOICEVOX のローカルエンジンでナレーションを合成する。

話者は**青山龍星**。既存2,845人の耳に合っている声なので変えない。
話者IDはバージョンで変わりうるのでハードコードせず、名前から引く。

  python scripts/narrate.py work/<id>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

ENGINE = "http://127.0.0.1:50021"
SPEAKER_NAME = "青山龍星"
STYLE_NAME = "ノーマル"
TIMEOUT = 120

# ショート動画の尺の許容範囲。script_writer.py の narration（350〜400字）を
# 素直に読み上げると文字数や句読点の量でこの範囲を外れることがあるため、
# synthesize() は実測してから speedScale を補正する（下記参照）。
TARGET_MIN = 56.0
TARGET_MAX = 61.0
TARGET_MID = (TARGET_MIN + TARGET_MAX) / 2  # 58.5秒。補正の基準値。

# speedScale の可動域。これより外は聞き取りづらくなるため、補正計算の
# 結果がこの範囲を超える場合はクランプする。
SPEED_MIN = 0.85
SPEED_MAX = 1.35

# 初回合成 + 最大この回数まで再合成する（合計で最大 MAX_RETRIES+1 回試行）。
MAX_RETRIES = 2

# この環境の VOICEVOX エンジンは GUI アプリではなく、エンジン単体の実行ファイル
# (run.exe) として配布・起動されている。配布形態によってインストール先が
# 変わるため、候補パスを並べて上から順に探す。
ENGINE_EXE_CANDIDATES = (
    Path.home() / "voicevox_engine" / "windows-cpu" / "run.exe",
    Path.home() / "voicevox_engine" / "windows-nvidia" / "run.exe",
    Path(r"C:\Program Files\VOICEVOX\VOICEVOX.exe"),
)


def resolve_speaker(speakers: list[dict], name: str,
                    style: str = STYLE_NAME) -> int:
    for sp in speakers:
        if sp.get("name") != name:
            continue
        for st in sp.get("styles") or []:
            if st.get("name") == style:
                return int(st["id"])
    raise ValueError(f"話者が見つかりません: {name}／{style}")


def ensure_engine() -> None:
    """エンジンの応答を確かめ、無ければ起動を試みる。

    ここで止めないと、後段（合成〜動画結合〜投稿）が無音のナレーション
    のまま進み、無音の動画が既存2,845人の視聴者に公開されてしまう。
    そのため「たぶん起動しているだろう」で先に進まず、必ず /version で
    実際に応答することを確認してから合成に入る。
    """
    try:
        requests.get(f"{ENGINE}/version", timeout=5).raise_for_status()
        return
    except Exception:                     # noqa: BLE001
        pass

    exe = next((p for p in ENGINE_EXE_CANDIDATES if p.exists()), None)
    if exe is None:
        raise RuntimeError(
            f"VOICEVOX のエンジンに接続できません: {ENGINE}\n"
            "自動起動できる実行ファイルも見つかりませんでした。"
            "候補パス:\n  " + "\n  ".join(str(p) for p in ENGINE_EXE_CANDIDATES) +
            "\nVOICEVOX エンジンを手動で起動してから再実行してください。"
        )

    print(f"- VOICEVOX が応答しないので起動します: {exe}")
    subprocess.Popen([str(exe)])
    for _ in range(30):
        time.sleep(2)
        try:
            requests.get(f"{ENGINE}/version", timeout=5).raise_for_status()
            return
        except Exception:             # noqa: BLE001
            continue
    raise RuntimeError(
        f"VOICEVOX のエンジンに接続できません: {ENGINE}\n"
        f"{exe} を起動しましたが応答がありませんでした。"
        "手動で起動状態を確認してください。"
    )


def _speaker_id() -> int:
    r = requests.get(f"{ENGINE}/speakers", timeout=TIMEOUT)
    r.raise_for_status()
    return resolve_speaker(r.json(), SPEAKER_NAME)


def wav_duration_seconds(wav_path: Path) -> float:
    """wav ファイルの実尺（秒）を返す。

    ffprobe 等の外部プロセスに依存せず、標準ライブラリの wave だけで
    フレーム数とサンプルレートから計算する純関数。単体テストしやすいように
    副作用は「ファイルを読む」だけにしている。
    """
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate == 0:
            return 0.0
        return frames / float(rate)


def _synthesize_once(text: str, sid: int, speed_scale: float, dest: Path) -> float:
    """speed_scale で1回合成して dest に書き、実尺（秒）を返す。"""
    q = requests.post(f"{ENGINE}/audio_query", timeout=TIMEOUT,
                      params={"text": text, "speaker": sid})
    q.raise_for_status()
    query = q.json()
    query["speedScale"] = speed_scale

    s = requests.post(f"{ENGINE}/synthesis", timeout=TIMEOUT,
                      params={"speaker": sid}, json=query)
    s.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(s.content)
    return wav_duration_seconds(dest)


def synthesize(text: str, dest: Path) -> Path:
    """text を読み上げた wav を dest に書く。

    無人実行なので、尺が56〜61秒の許容範囲から外れたまま気づかずに
    投稿されると、ensure_engine() が防いでいる「無音動画を無自覚に
    投稿する」のと同じ構造の失敗になる。そのため:

      1. まず speedScale=1.0 で合成し、実尺を wav_duration_seconds() で測る。
      2. 範囲外なら「実尺 ÷ 目標中央値(58.5秒)」の比で speedScale を
         補正し、最大 MAX_RETRIES 回まで再合成する。
      3. それでも収まらない場合は例外にせず最後の結果を採用する。
         このチャンネルの収益化条件は「90日で3本以上の投稿」なので、
         数秒尺がずれた動画を出すより1本を落とすほうが損失が大きい。
         ただし気づけないと同じ問題を繰り返すため、必ず警告を出す。
    """
    ensure_engine()
    sid = _speaker_id()

    speed = 1.0
    duration = 0.0
    for attempt in range(1, MAX_RETRIES + 2):  # 初回 + 最大 MAX_RETRIES 回の再試行
        duration = _synthesize_once(text, sid, speed, dest)
        in_range = TARGET_MIN <= duration <= TARGET_MAX
        print(f"- 試行{attempt}: speedScale={speed:.3f} → 実尺{duration:.2f}秒"
              f"{'（許容範囲内）' if in_range else ''}")
        if in_range:
            return dest
        if attempt == MAX_RETRIES + 1:
            break
        new_speed = speed * (duration / TARGET_MID)
        new_speed = max(SPEED_MIN, min(SPEED_MAX, new_speed))
        print(f"  56〜61秒の範囲外のため speedScale を "
              f"{speed:.3f} → {new_speed:.3f} に補正して再合成します")
        speed = new_speed

    print(f"! 警告: {MAX_RETRIES}回再試行しても尺が56〜61秒に収まりませんでした"
          f"（実尺{duration:.2f}秒, speedScale={speed:.3f}）。"
          "この結果のまま採用します（収益化条件＝90日3本以上を優先し、"
          "1本落とすより尺が多少ずれる方を選ぶ）。要確認。")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    a = ap.parse_args()

    script = json.loads((a.workdir / "script.json").read_text(encoding="utf-8"))
    out = synthesize(script["narration"], a.workdir / "voice.wav")
    print(f"✓ {out.name}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
