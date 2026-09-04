#!/usr/bin/env python3
"""選挙期間中の1本を作って予約する（候補者の公約ページを一次資料にする）。

`run_daily.py` とは**別の実行入口**。違うのは一次資料の出どころだけで
（scripts/election.py の許可リスト）、台本より後ろ——引用カードの検証・
音声合成・動画合成・アップロード——は run_daily と**同じ関数**を呼ぶ。
検証をこちら側に書き写すと、同じ概念の基準が2箇所に散る
（CLAUDE.md「判定基準を2箇所に書かない」）。

画面のカードは必ず引用カードになる（`Evidence.figure` を空で作る）。
公約ページの数値目標は、数値カードに出すと「一次資料の出典キャプションが
付いた、書き手が選んだ数字」になる。引用カードなら出るのは
**ページに逐語で存在する文字列だけ**で、それを election.collect と
ground_excerpt が二重に確かめる。

選挙が終わったら、このファイルと scripts/election.py を消せば元の1経路に戻る。

使い方:
    python scripts/run_election.py --candidate koja \
        --script work/scripts/koja_manifest.json \
        --slot 2026-09-02T18:30:00+09:00
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import election                                    # noqa: E402
from scripts.build_short import build                           # noqa: E402
from scripts.evidence import build_recipe                       # noqa: E402
from scripts.narrate import synthesize                          # noqa: E402
from scripts.run_daily import (CHANNEL_ID, JST, ensure_grounded_card,  # noqa: E402
                               ensure_photo, taken_slots)
from scripts.script_writer import ScriptMismatch, load_script    # noqa: E402

WORK = ROOT / "work"
RECIPES = ROOT / "recipes"

# 2026年沖縄県知事選の届け出者数（2026-08-27 告示時点で6人・過去最多）。
# 説明文に書くために持っている。MANIFESTO_SOURCES に載っているのはこのうち
# 2氏だけなので、**リンクの数を候補者数と読ませない**ためにここを明示する。
CANDIDATE_COUNT = 6


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", required=True,
                    choices=sorted(election.MANIFESTO_SOURCES),
                    help="公約ページの許可リストのキー")
    ap.add_argument("--script", required=True,
                    help="台本JSON。source_url と source_quote が必須")
    ap.add_argument("--slot", required=True,
                    help="公開予定時刻（ISO8601, 例 2026-09-02T18:30:00+09:00）")
    ap.add_argument("--id", help="work/<id>。既定は candidate と枠から作る")
    ap.add_argument("--dry-run", action="store_true",
                    help="動画までは作るがアップロードしない")
    a = ap.parse_args(argv)

    a.slot = datetime.fromisoformat(a.slot)
    if a.slot.tzinfo is None:
        a.slot = a.slot.replace(tzinfo=JST)
    if not a.id:
        a.id = f"election-{a.candidate}-{a.slot.strftime('%m%d%H%M')}"
    return a


def write_meta(workdir: Path, script, license_: dict, ev) -> None:
    """meta.json と description.txt を書く。

    説明文には**両候補の公式サイトを併記する**。選挙期間中に一方の候補の
    公約だけを説明文に置くと、動画単体では対になっている相手が見えない。
    """
    (workdir / "meta.json").write_text(json.dumps({
        "id": workdir.name,
        "title": script.title[:100],
        "tags": script.tags,
        "category_id": "25",
        "expected_channel_id": CHANNEL_ID,
        "privacy_status": "private",
        "source_url": ev.source_url,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 候補ごとに1行にまとめる。MANIFESTO_SOURCES は1人につき複数（要約ページと
    # 政策集PDF）を持つので、そのまま並べると同じ人が2回出る。
    by_person: dict[str, str] = {}
    for s in election.MANIFESTO_SOURCES.values():
        by_person.setdefault(s.person, s.url)
    others = "\n".join(f"・{person}: {url}" for person, url in by_person.items())

    (workdir / "description.txt").write_text("\n".join([
        script.narration,
        "",
        f"根拠: {ev.context}",
        ev.source_url,
        "",
        "2026年沖縄県知事選挙（2026年9月13日投開票）の候補者が公表している"
        "公約から、書かれている内容をそのまま紹介しています。",
        # **立候補者数を明記する。** ここに2人ぶんのリンクだけを置くと、
        # 動画単体では「候補は2人」と読める。実際の届け出は6人
        # （2026-08-27 告示・過去最多）なので、リンクが2人ぶんである理由
        # ——公約の全文を公式サイトで公表しているのがこの2氏——まで書く。
        f"この選挙には{CANDIDATE_COUNT}人が立候補しています。"
        "この動画で扱うのは、公約の全文を公式サイトで公表している次の2氏です。",
        others,
        "",
        license_["attribution"],
    ]) + "\n", encoding="utf-8")


def main() -> None:
    a = parse_args()
    src = election.MANIFESTO_SOURCES[a.candidate]

    if a.slot <= datetime.now(JST):
        sys.exit(f"✗ 枠 {a.slot.isoformat()} はすでに過ぎています")
    if a.slot in taken_slots():
        sys.exit(f"✗ 枠 {a.slot.isoformat()} はすでに埋まっています")

    # 台本ファイルから逐語引用の宣言を読む。ここで読むのは source_quote だけで、
    # 本文の検証は load_script（source_url の突き合わせ）と
    # ensure_grounded_card（引用カードの grounding）が行う。
    raw = json.loads(Path(a.script).read_text(encoding="utf-8"))
    quote = (raw.get("source_quote") or "").strip()
    if not quote:
        sys.exit(f"✗ 台本ファイルに source_quote がありません: {a.script}。"
                 "公約ページに逐語で存在する引用を書いてください")

    # 一次資料の関門。引用がページに逐語で無ければここで止まる。
    try:
        ev = election.collect(a.candidate, quote)
    except (election.UnknownCandidate, election.QuoteNotFound) as e:
        sys.exit(f"✗ 一次資料の関門で止まりました: {e}")
    print(f"- 一次資料: {ev.context}")
    print(f"  {ev.source_url}")
    print(f"  引用（逐語で確認済み）: {ev.quote[:60]}")

    workdir = WORK / a.id
    workdir.mkdir(parents=True, exist_ok=True)

    photo, license_path = workdir / "photo.jpg", workdir / "license.json"
    if not (photo.exists() and license_path.exists()):
        license_rec = ensure_photo(ev, photo)
        license_path.write_text(
            json.dumps(license_rec, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    recipe = build_recipe({"id": a.id, "title": raw.get("headline", ""),
                           "keyword": a.candidate, "category": "election"}, ev)
    RECIPES.mkdir(parents=True, exist_ok=True)
    (RECIPES / f"{a.id}.json").write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    try:
        script = load_script(a.script, recipe["evidence"])
    except ScriptMismatch as e:
        sys.exit(f"✗ 渡された台本をこの一次資料に使えません: {e}")

    synthesize(script.narration, workdir / "voice.wav")
    script = ensure_grounded_card(script, recipe["evidence"])

    license_ = json.loads(license_path.read_text(encoding="utf-8"))
    (workdir / "script.json").write_text(
        script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    write_meta(workdir, script, license_, ev)
    build(workdir)

    if a.dry_run:
        print(f"✓ dry-run: {workdir / 'video.mp4'} を作りました（未投稿）")
        return

    subprocess.run([sys.executable, "scripts/upload_youtube.py", str(workdir)],
                   check=True, cwd=ROOT)
    if a.slot <= datetime.now(JST):
        sys.exit(f"! 枠 {a.slot.isoformat()} を過ぎたため予約しませんでした。"
                 f"private のまま残っています: {workdir}")
    subprocess.run([sys.executable, "scripts/upload_youtube.py", str(workdir),
                    "--schedule", a.slot.isoformat()], check=True, cwd=ROOT)
    print(f"✓ {a.slot.strftime('%m/%d %H:%M')} に予約しました: {workdir}")


if __name__ == "__main__":
    main()
