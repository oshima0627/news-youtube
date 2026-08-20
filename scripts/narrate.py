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
if hasattr(sys.stderr, "reconfigure"):
    # 失敗の原因は stderr に出す。Windows 既定のロケール（cp932）のままだと
    # 日本語の原因メッセージだけが文字化けし、「原因がログにそのまま出る」
    # という各CLIの die()／中止メッセージの目的が損なわれる。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.telop import split_segments  # noqa: E402

ENGINE = "http://127.0.0.1:50021"
SPEAKER_NAME = "青山龍星"
STYLE_NAME = "ノーマル"
TIMEOUT = 120

# /synthesis だけ別枠にする。話者一覧やモーラ数の取得（audio_query）は
# 実測で1秒未満だが、**合成そのものは音声1秒あたり約1.8秒かかる**
# （CPU版エンジンの実測: 63.5秒の音声で115.9秒）。TIMEOUT=120 を合成にも
# 使っていたため余裕が4秒しかなく、他プロセスの負荷で容易に超えた。
# 超えると synthesize() が例外を送出し、run_daily.py はそれを
# 「VOICEVOX未起動」＝環境不備と判断して**日次実行ごと中止**するため、
# 合成の遅さがそのまま「本日0本」になる（実際に2回連続で起きた）。
# エンジンが死んでいる場合は ensure_engine() が /version を5秒で先に
# 弾くので、ここを長くしても気づけなくなることはない。
SYNTHESIS_TIMEOUT = 600

# ショート動画の尺の許容範囲。script_writer.py の narration（330〜355字）を
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

# 読み上げ1字あたりの秒数（speedScale=1.0）。実測（2026-08-13、青山龍星
# ノーマル、本番の台本6本）で 0.165〜0.181、平均 0.171。
#
# **尺合わせには使わない。** 本文ごとに ±6% 動くのに対し、狙う窓は
# 58.5±2.5秒＝±4.3% とそれより狭く、字数からの推定では窓に入りきらない
# （実際、推定に切り替えた後も2本中1本が55.41秒で下振れした）。尺は
# query_duration() が audio_query から計算する。
#
# この値は台本に頼む字数（script_writer.NARRATION_MIN/MAX_CHARS）を
# 決めるためだけに残してある。速度補正が可動域に張り付かない長さの本文を
# 書いてもらうための目安で、tests/test_script_writer.py が両者を縛っている。
SECONDS_PER_CHAR = 0.171

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


def query_path(dest: Path) -> Path:
    """wav と対になる audio_query の保存先（voice.wav → voice_query.json）。"""
    return dest.with_name(dest.stem + "_query.json")


def segments_path(dest: Path) -> Path:
    """区切りごとのモーラ数の保存先（voice.wav → voice_segments.json）。"""
    return dest.with_name(dest.stem + "_segments.json")


def count_moras(text: str, sid: int) -> int:
    """その文字列を読んだときのモーラ数。"""
    r = requests.post(f"{ENGINE}/audio_query", timeout=TIMEOUT,
                      params={"text": text, "speaker": sid})
    r.raise_for_status()
    return sum(len(p.get("moras") or []) for p in r.json().get("accent_phrases") or [])


def measure_segments(text: str, sid: int) -> list[dict]:
    """本文の区切りごとに (本文, モーラ数) を測る。

    テロップを音に合わせるための対応づけに使う（scripts/telop.py）。
    区切りの**数**ではなく**モーラ数**を鍵にするのは、VOICEVOX が句読点以外の
    場所にも間を入れるため区切りの数が本文と食い違うから（実測3本中2本で
    食い違った）。読み方の総量は切って数えても一括で数えても変わらない。
    """
    return [{"text": seg, "moras": count_moras(seg, sid)}
            for seg in split_segments(text)]


def fetch_query(text: str, sid: int) -> dict:
    """読み方（audio_query）を引く。合成より桁違いに速い（実測1秒未満）。"""
    r = requests.post(f"{ENGINE}/audio_query", timeout=TIMEOUT,
                      params={"text": text, "speaker": sid})
    r.raise_for_status()
    return r.json()


def query_duration(query: dict) -> float:
    """その audio_query で合成したときの尺（秒）。**合成せずに分かる。**

    audio_query はモーラごとの子音長・母音長と句間の間（pause_mora）、
    前後の無音（prePhonemeLength / postPhonemeLength）を持っている。
    合計を speedScale で割ったものが実尺になる。

    既存11本で実際の wav と突き合わせて誤差は最大0.17秒だった
    （テストの fixture ではなく本番の voice_query.json と voice.wav）。

    字数からの推定（SECONDS_PER_CHAR）ではここまで当たらない。読み方の
    速さは本文によって ±6% ほど動くのに対し、狙う窓は 58.5±2.5秒＝±4.3% と
    それより狭い。実際、推定に切り替えた後も2本中1本が窓を外した
    （55.41秒＝下振れ）。推定をやめて実際の読み方から計算する。
    """
    speed = query.get("speedScale") or 1.0
    total = ((query.get("prePhonemeLength") or 0)
             + (query.get("postPhonemeLength") or 0))
    for phrase in query.get("accent_phrases") or []:
        for mora in phrase.get("moras") or []:
            total += ((mora.get("consonant_length") or 0)
                      + (mora.get("vowel_length") or 0))
        pause = phrase.get("pause_mora")
        if pause:
            total += pause.get("vowel_length") or 0
    return total / speed


def fit_speed(query: dict, target_mid: float = TARGET_MID) -> float:
    """尺を目標中央値（既定は58.5秒）に合わせる speedScale。可動域に収める。

    `target_mid` は長尺のパート（75秒前後）でも同じ計算を使うための引数。
    既定値はショートの中央値のままなので、既存の呼び出しは変わらない。

    基準にするのは **speedScale=1.0 で読んだときの尺**。`_synthesize_once` は
    求めた値を絶対値として上書きするので、query が既に持っている speedScale
    ごと打ち消しておかないと、audio_query が 1.0 以外を返した瞬間に倍率ぶん
    ずれた答えを出す（VOICEVOX の既定は 1.0 だが、既定値はエンジン側の都合で
    変わりうる。読み方は同じなのに答えが変わる形の壊れ方は気づきにくい）。
    """
    base = query_duration({**query, "speedScale": 1.0})
    if base <= 0:
        return 1.0
    return max(SPEED_MIN, min(SPEED_MAX, base / target_mid))


def _synthesize_once(query: dict, sid: int, speed_scale: float, dest: Path) -> float:
    """speed_scale で1回合成して dest に書き、実尺（秒）を返す。

    合成に使った audio_query も隣に残す。この中のモーラごとの子音長・母音長が
    そのまま「どの句が何秒目に読まれるか」なので、テロップの割り付け
    （scripts/telop.py）はこれを読む。音声認識も強制アライメントも要らない。
    採用された speedScale の分だけ残るよう、再合成のたびに上書きする。
    """
    query = dict(query)
    query["speedScale"] = speed_scale

    s = requests.post(f"{ENGINE}/synthesis", timeout=SYNTHESIS_TIMEOUT,
                      params={"speaker": sid}, json=query)
    s.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(s.content)
    query_path(dest).write_text(json.dumps(query, ensure_ascii=False),
                                encoding="utf-8")
    return wav_duration_seconds(dest)


def synthesize(text: str, dest: Path, *,
               target_min: float = TARGET_MIN,
               target_max: float = TARGET_MAX) -> Path:
    """text を読み上げた wav を dest に書く。

    `target_min` / `target_max` は許容する実尺の窓。既定はショートの
    56〜61秒で、長尺のパート（75秒前後・導入は12秒前後）は呼び出し側が
    渡す。窓を固定したままだと長尺では毎回「範囲外」の警告が出て、
    本物の異常（無音・合成失敗）がその警告に埋もれる。

    無人実行なので、尺が56〜61秒の許容範囲から外れたまま気づかずに
    投稿されると、ensure_engine() が防いでいる「無音動画を無自覚に
    投稿する」のと同じ構造の失敗になる。そのため:

      1. 読み方（audio_query）を1回引き、そこから**合成せずに**尺を計算して
         （query_duration）speedScale を決める。誤差は実測で最大0.17秒なので、
         この1回で必ず範囲に入る。
      2. それでも範囲外なら「実尺 ÷ 目標中央値(58.5秒)」の比で speedScale を
         補正し、最大 MAX_RETRIES 回まで再合成する。エンジンの仕様変更などで
         計算が合わなくなったときの安全網として残す（通常は発火しない）。
      3. それでも収まらない場合は例外にせず最後の結果を採用する。
         このチャンネルの収益化条件は「90日で3本以上の投稿」なので、
         数秒尺がずれた動画を出すより1本を落とすほうが損失が大きい。
         ただし気づけないと同じ問題を繰り返すため、必ず警告を出す。
    """
    if target_min > target_max:
        # 取り違えたまま走ると、どの実尺でも「範囲外」になって毎回
        # 再合成する（本番尺で数分の空費）。その場で止める。
        raise ValueError(
            f"尺の窓の指定が逆です: target_min={target_min} > target_max={target_max}")

    target_mid = (target_min + target_max) / 2
    ensure_engine()
    sid = _speaker_id()

    query = fetch_query(text, sid)
    speed = fit_speed(query, target_mid)
    duration = 0.0
    for attempt in range(1, MAX_RETRIES + 2):  # 初回 + 最大 MAX_RETRIES 回の再試行
        duration = _synthesize_once(query, sid, speed, dest)
        in_range = target_min <= duration <= target_max
        print(f"- 試行{attempt}: speedScale={speed:.3f} → 実尺{duration:.2f}秒"
              f"{'（許容範囲内）' if in_range else ''}")
        if in_range:
            _write_segments(text, sid, dest)
            return dest
        if attempt == MAX_RETRIES + 1:
            break
        new_speed = speed * (duration / target_mid)
        new_speed = max(SPEED_MIN, min(SPEED_MAX, new_speed))
        print(f"  {target_min:.0f}〜{target_max:.0f}秒の範囲外のため speedScale を "
              f"{speed:.3f} → {new_speed:.3f} に補正して再合成します")
        speed = new_speed

    print(f"! 警告: {MAX_RETRIES}回再試行しても尺が"
          f"{target_min:.0f}〜{target_max:.0f}秒に収まりませんでした"
          f"（実尺{duration:.2f}秒, speedScale={speed:.3f}）。"
          "この結果のまま採用します（収益化条件＝90日3本以上を優先し、"
          "1本落とすより尺が多少ずれる方を選ぶ）。要確認。")
    _write_segments(text, sid, dest)
    return dest


def _write_segments(text: str, sid: int, dest: Path) -> None:
    """区切りごとのモーラ数を書き出す。失敗してもwavは捨てない。

    ここで落ちても動画は作れる（テロップが静止字幕になるだけ）。
    合成し直すほうが高くつくので、警告に留める。
    """
    try:
        segments = measure_segments(text, sid)
    except Exception as e:            # noqa: BLE001
        print(f"! テロップ用の区切りを測れませんでした（静止字幕になります）: {e}")
        return
    segments_path(dest).write_text(
        json.dumps(segments, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    a = ap.parse_args()

    script = json.loads((a.workdir / "script.json").read_text(encoding="utf-8"))
    out = synthesize(script["narration"], a.workdir / "voice.wav")
    print(f"✓ {out.name}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
