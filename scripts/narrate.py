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


def synthesize(text: str, dest: Path) -> Path:
    """text を読み上げた wav を dest に書く。"""
    ensure_engine()
    sid = _speaker_id()
    q = requests.post(f"{ENGINE}/audio_query", timeout=TIMEOUT,
                      params={"text": text, "speaker": sid})
    q.raise_for_status()
    query = q.json()
    # 350〜400字の台本（script_writer.py の narration 想定文字数）を実測した結果、
    # 等倍(1.0)で56〜61秒の目標尺に収まった。1.15では約51秒まで縮んで短すぎたため
    # 既定値を等倍に変更している。
    query["speedScale"] = 1.0

    s = requests.post(f"{ENGINE}/synthesis", timeout=TIMEOUT,
                      params={"speaker": sid}, json=query)
    s.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(s.content)
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
