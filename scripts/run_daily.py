#!/usr/bin/env python3
"""1日分を作って予約公開まで通す。

  python scripts/run_daily.py
  python scripts/run_daily.py --dry-run   # アップロードだけ飛ばす

タスクスケジューラから毎朝1回呼ばれる。当日のまだ来ていない枠の数だけ作り、
YouTube側の予約公開に載せて終わる。PCが日中落ちていても定刻に公開される。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    # 環境不備での中止メッセージ（die/abort）は stderr に出す。既定の Windows
    # ロケール（cp932）のままだと日本語の原因メッセージが文字化けし、
    # 「原因が明確に出る」という本タスクの目的そのものを損なうため、
    # stdout と同様に reconfigure する。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

WORK = ROOT / "work"
RECIPES = ROOT / "recipes"
CANDIDATES = WORK / "candidates.json"
SEEN = ROOT / "state" / "seen.json"
STREAK = ROOT / "state" / "empty_streak.json"
CHANNEL_ID = "UCYHTfHJOoETzvpx-VZlUTng"

from scripts.build_short import build  # noqa: E402
from scripts.evidence import collect  # noqa: E402
from scripts.narrate import synthesize  # noqa: E402
from scripts.script_writer import write  # noqa: E402
from scripts.slots import pending_slots  # noqa: E402


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def _bump_empty_streak(made: int) -> None:
    """0本の日が続いたら警告する。収益化要件は90日で3本以上。"""
    n = 0 if made else (json.loads(STREAK.read_text(encoding="utf-8"))["days"]
                        if STREAK.exists() else 0) + 1
    STREAK.parent.mkdir(parents=True, exist_ok=True)
    STREAK.write_text(json.dumps({"days": n}) + "\n", encoding="utf-8")
    if n >= 3:
        print(f"! {n}日続けて0本です。RSSの配点か採用ゲートを見直してください")


def _write_meta(workdir: Path, script, license_: dict, evidence: dict) -> None:
    # 予約時刻（slot）はここには持たせない。予約は upload_youtube.py の
    # --schedule 引数にその場で渡すだけで、meta.json や状態として
    # 保持しておく必要が無いため（使わない引数を増やすと後から
    # 「これは何のためにあるのか」を調べる負債になる）。
    (workdir / "meta.json").write_text(json.dumps({
        "id": workdir.name,
        "title": script.title[:100],
        "tags": script.tags,
        "category_id": "25",
        "expected_channel_id": CHANNEL_ID,
        "privacy_status": "private",
        "source_url": evidence["source_url"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (workdir / "description.txt").write_text("\n".join([
        script.narration,
        "",
        f"根拠: {evidence['context']}",
        evidence["source_url"],
        "",
        license_["attribution"],
    ]) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="台本・音声・動画までは作るが、YouTubeへのアップロードは行わない")
    a = ap.parse_args()

    slots = pending_slots(datetime.now())
    if not slots:
        print("本日の枠は過ぎています。明朝に回します")
        return
    print(f"- 本日の残り枠: {[s.strftime('%H:%M') for s in slots]}")

    subprocess.run([sys.executable, "scripts/collect_news.py",
                    "--limit", "20"], check=True, cwd=ROOT)
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))

    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))
               if SEEN.exists() else [])
    made = 0
    aborted = False

    try:
        for cand in candidates:
            if made >= len(slots):
                break
            found = collect(cand["keyword"])
            if not found:
                print(f"- 見送り（根拠なし）: {cand['title'][:32]}")
                continue
            ev = found[0]

            workdir = WORK / cand["id"]
            recipe = {"id": cand["id"], "headline": cand["title"],
                      "keyword": cand["keyword"], "category": cand["category"],
                      "evidence": ev.__dict__}
            RECIPES.mkdir(parents=True, exist_ok=True)
            (RECIPES / f"{cand['id']}.json").write_text(
                json.dumps(recipe, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")

            # 画像（photo.jpg / license.json）は題材ごとに人物・場面が違うため、
            # fetch_photo.py で手作業で用意しておく運用になっている
            # （scripts/photos.py のホワイトリストの都合で自動解決していない）。
            # 無いまま台本生成・音声合成に進むと、後で必ず失敗するとわかっている
            # 処理に Anthropic API の課金と VOICEVOX の時間を使うだけになるので、
            # ここで先に確認してこの題材だけ飛ばす。
            photo = workdir / "photo.jpg"
            license_path = workdir / "license.json"
            missing = [n for n, p in (("photo.jpg", photo),
                                      ("license.json", license_path))
                      if not p.exists()]
            if missing:
                print(f"- 見送り（画像未準備: {', '.join(missing)}）: "
                      f"{cand['id']} {cand['title'][:32]}\n"
                      f"  python scripts/fetch_photo.py work/{cand['id']} "
                      "<画像URL> で用意してから次回の実行で拾われます")
                continue

            # 台本生成（write）と音声合成（synthesize）は、この題材固有の事情
            # ではなく ANTHROPIC_API_KEY や VOICEVOX の起動状態という「環境」に
            # 依存する。環境が壊れていれば1件目から確実に同じ理由で落ちる。
            # ここを他の失敗（build() の画像合成やアップロードの一時的なエラー
            # など、題材固有で起きうる失敗）と同列に「この題材だけ飛ばして次へ」
            # にすると、全候補ぶん同じ失敗を繰り返した末に「本日 0/2 本」とだけ
            # 表示されて、ログを見るまで原因が環境不備だと気づけない。
            # そのためこの2関数の失敗だけは題材を飛ばさず、日次実行全体を
            # その場で中止して原因をそのまま出す。
            try:
                script = write(recipe)
                synthesize(script.narration, workdir / "voice.wav")
            except Exception as e:                # noqa: BLE001
                print(f"✗ 台本生成または音声合成が失敗しました。"
                      "ANTHROPIC_API_KEY が未設定／無効か、VOICEVOXが起動して"
                      "いないなど、環境不備の可能性が高いため日次実行を"
                      f"中止します: {e}", file=sys.stderr)
                aborted = True
                break

            # ここから先（動画合成・アップロード）は画像やffmpeg、YouTube側の
            # 一時的なエラーなど題材固有の要因で失敗しうる。1本の失敗で当日を
            # 全部落とさない。work/ は残るので次回リトライできる
            try:
                license_ = json.loads(license_path.read_text(encoding="utf-8"))
                (workdir / "script.json").write_text(
                    script.model_dump_json(indent=2) + "\n", encoding="utf-8")
                _write_meta(workdir, script, license_, ev.__dict__)
                build(workdir)

                if not a.dry_run:
                    subprocess.run([sys.executable, "scripts/upload_youtube.py",
                                    str(workdir)], check=True, cwd=ROOT)
                    subprocess.run(
                        [sys.executable, "scripts/upload_youtube.py",
                         str(workdir), "--schedule",
                         slots[made].strftime("%Y-%m-%dT%H:%M:%S+09:00")],
                        check=True, cwd=ROOT)
            except Exception as e:                # noqa: BLE001
                print(f"! 失敗しました（この題材は飛ばします）: {cand['id']} {e}")
                continue

            # 投稿が通ってから既出に入れる。失敗した題材は次回また拾えるようにする
            seen.add(cand["id"])
            made += 1
            print(f"✓ {made}/{len(slots)} {script.title[:40]}")
    finally:
        # 中止した場合でも、そこまでに投稿できた分は既出として残す
        SEEN.parent.mkdir(parents=True, exist_ok=True)
        SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    print(f"本日 {made}/{len(slots)} 本")
    if aborted:
        sys.exit(1)
    # 環境不備での中断は「題材が無い」わけではないので streak には数えない
    _bump_empty_streak(made)


if __name__ == "__main__":
    main()
