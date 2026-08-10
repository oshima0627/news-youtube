"""一時スクリプト: 350〜400字の本番相当ナレーションと、
wavが上限付近(60秒前後)になるケースの両方でbuild_short.build()を検証する。
確認後に削除する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_short import build, mp4_duration_seconds  # noqa: E402
from scripts.narrate import (_speaker_id, _synthesize_once,  # noqa: E402
                             ensure_engine, synthesize, wav_duration_seconds)

NARRATION_A = (
    "防衛省の発表によると、東シナ海の公海上空で中国軍のフリゲート艦が"
    "海上自衛隊の護衛艦に対して火器管制レーダーを照射したことが確認された。"
    "火器管制レーダーの照射は、相手に攻撃の意図があると受け取られかねない"
    "極めて危険な行為であり、過去にも同種の事案が外交問題に発展している。"
    "防衛省は中国側に厳重に抗議するとともに、再発防止を強く求める方針を示した。"
    "国会の答弁でも、この問題については与野党を超えて懸念の声が上がっており、"
    "今後の日中関係や地域の安全保障環境にどのような影響を及ぼすのか、"
    "引き続き注視が必要な状況が続いている。政府は関係国とも緊密に連携し、"
    "情報収集と警戒監視の体制を強化する方針である。防衛大臣は記者会見で、"
    "自衛隊員の安全確保を最優先にしつつ、冷静かつ毅然とした対応を続けると述べた。"
)

workdir = ROOT / "work" / "_smoke"


def setup_common(mode: str) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    if mode == "landscape":
        Image.new("RGB", (1920, 1080), (60, 90, 140)).save(workdir / "photo.jpg")
    else:
        Image.new("RGB", (900, 1600), (140, 60, 90)).save(workdir / "photo.jpg")

    script = {
        "headline": "中国軍機がレーダー照射",
        "narration": NARRATION_A,
        "figure_label": "照射回数",
        "figure_value": "1回",
        "title": "中国軍機がレーダー照射、防衛省が抗議",
        "tags": ["安全保障", "防衛省"],
    }
    (workdir / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    license_ = {"attribution": "写真: サンプル画像（スモークテスト用ダミー）\nCC0"}
    (workdir / "license.json").write_text(
        json.dumps(license_, ensure_ascii=False, indent=2), encoding="utf-8")

    recipe = {
        "evidence": {"context": "第213回国会 衆議院 安全保障委員会 2026年3月5日 ○○委員発言"}
    }
    (ROOT / "recipes" / "_smoke.json").write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")


print(f"NARRATION_A length: {len(NARRATION_A)}字")

# --- ケースA: 350〜400字の本番相当ナレーションで通常合成 ---
print("\n=== ケースA: 350〜400字ナレーション（通常のsynthesize()）===")
setup_common("landscape")
synthesize(NARRATION_A, workdir / "voice.wav")
wav_a = wav_duration_seconds(workdir / "voice.wav")
out_a = build(workdir)
mp4_a = mp4_duration_seconds(out_a)
print(f"[結果A] wav={wav_a:.2f}秒 mp4={mp4_a:.2f}秒 差={mp4_a - wav_a:+.2f}秒")

# --- ケースB: wavが上限付近(60秒前後)になるように強制 ---
print("\n=== ケースB: wavを60秒前後に強制してbuild ===")
ensure_engine()
sid = _speaker_id()
# まずspeed=1.0で基準の実尺を測り、60.3秒を狙うspeedScaleを逆算する。
base_dur = _synthesize_once(NARRATION_A, sid, 1.0, workdir / "voice.wav")
target = 60.3
speed_for_target = max(0.85, min(1.35, base_dur / target))
wav_b = _synthesize_once(NARRATION_A, sid, speed_for_target, workdir / "voice.wav")
print(f"  speed={speed_for_target:.3f} で wav実尺={wav_b:.2f}秒")
out_b = build(workdir)
mp4_b = mp4_duration_seconds(out_b)
print(f"[結果B] wav={wav_b:.2f}秒 mp4={mp4_b:.2f}秒 差={mp4_b - wav_b:+.2f}秒")

print("\n=== まとめ ===")
print(f"A: wav={wav_a:.2f}s mp4={mp4_a:.2f}s diff={mp4_a - wav_a:+.2f}s")
print(f"B: wav={wav_b:.2f}s mp4={mp4_b:.2f}s diff={mp4_b - wav_b:+.2f}s")
