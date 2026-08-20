#!/usr/bin/env python3
"""長尺（16:9・約4分）を1本作って予約公開まで通す。

  python scripts/run_long.py --only <候補ID> --only <候補ID> --only <候補ID>
  python scripts/run_long.py --keyword "空き家 住宅 対策" --keyword "..." --keyword "..."

**題材は人が選ぶ。** 採用ゲート（evidence.collect）は「検索語が同じ文脈に
2語以上固まって現れるか」しか見ておらず、見出しと引用が噛み合っているかは
判定していない（CLAUDE.md 未解決項目）。候補の先頭から機械的に採ると、
噛み合わない題材がそのまま公開まで到達する（docs/known-issues.md 5番・5-b番、
予約公開まで行った実例が2件）。3題材を束ねる長尺では、その1本ぶんの被害が
3倍になるため、`--only` / `--keyword` を必須にしてある。

枠は1日1本・JST 18:00（slots.LONG_SLOTS）。ショートの枠（07:30 / 18:30）
とは別に取る。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

WORK = ROOT / "work"
RECIPES = ROOT / "recipes"
CANDIDATES = WORK / "candidates.json"
SEEN = ROOT / "state" / "seen.json"
CHANNEL_ID = "UCYHTfHJOoETzvpx-VZlUTng"

JST = timezone(timedelta(hours=9))

from scripts.build_long import (INTRO_TARGET_MAX, INTRO_TARGET_MIN,  # noqa: E402
                                OUTRO_TARGET_MAX, OUTRO_TARGET_MIN,
                                SEGMENT_TARGET_MAX, SEGMENT_TARGET_MIN,
                                build, chapters)
from scripts.sources import make_id  # noqa: E402
from scripts.evidence import (EvidenceSourcesUnavailable, build_recipe,  # noqa: E402
                              collect, ground_excerpt)
from scripts.narrate import synthesize, wav_duration_seconds  # noqa: E402
from scripts.run_daily import (SAME_TOPIC_OVERLAP, USED_LOOKBACK_DAYS,  # noqa: E402
                               ensure_photo, load_used, save_used, taken_slots)
from scripts.script_writer import (ScriptGenerationRejected,  # noqa: E402
                                   ScriptWriterUnavailable, intro_narration,
                                   outro_narration, write_long_meta,
                                   write_segment)
from scripts.slots import pending_slots  # noqa: E402
from scripts.upload_youtube import (EXIT_CHANNEL_MISMATCH,  # noqa: E402
                                    EXIT_CHANNEL_UNVERIFIED)

# 題材の数。3本立てを標準にするが、途中で1件落ちても作れるようにしてある
# （枠を空けるより出すほうを選ぶ、というこのチャンネルの方針に合わせる）。
SEGMENTS_MIN = 2
SEGMENTS_MAX = 5

INTRO_HEADLINE = "きょうの論点"
OUTRO_HEADLINE = "まとめ"


def resolve_candidates(only: list[str], keywords: list[str],
                       limit: int) -> list[dict]:
    """人が指定した題材を、候補の形（id / title / keyword / category）で返す。

    `--only` は collect_news.py が書く候補から選ぶ。`--keyword` は RSS を
    通らず検索語をそのまま題材にする（run_daily.py の同名の引数と同じ扱いで、
    題材名には検索語をそのまま使う — 人が書いた見出しを入れると、一次資料に
    無い出来事を台本の前提にしてしまう）。
    """
    picked: list[dict] = []

    if only:
        try:
            subprocess.run([sys.executable, "scripts/collect_news.py",
                            "--limit", str(limit)], check=True, cwd=ROOT)
        except subprocess.CalledProcessError as e:
            print(f"✗ 候補の収集に失敗しました（終了コード {e.returncode}）",
                  file=sys.stderr)
            sys.exit(1)
        candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
        by_id = {c["id"]: c for c in candidates}
        for wanted in only:
            if wanted not in by_id:
                # 黙って飛ばすと、人が選んだのとは違う本数・違う題材で
                # 1本できあがる。その場で止める（run_daily.py と同じ判断）。
                print(f"✗ --only {wanted} に一致する候補がありません"
                      f"（候補{len(candidates)}件）。RSSの再取得で入れ替わった"
                      f"可能性があります。--candidates を広げるか、"
                      f"python scripts/yield_report.py --refresh で"
                      f"取り直してください", file=sys.stderr)
                sys.exit(1)
            picked.append(by_id[wanted])

    for keyword in keywords:
        picked.append({"id": make_id(keyword), "title": keyword,
                       "keyword": keyword, "category": "政治"})

    return picked


def prepare_segment(cand: dict, workdir: Path, index: int,
                    used_sources: set[str], used_keywords: list[set[str]],
                    seen: set[str]) -> dict | None:
    """1題材ぶんを、採用ゲート → 画像 → 台本まで通す。作れなければ None。

    失敗の扱いは run_daily.py と同じ約束にしてある:
      - 環境不備（ScriptWriterUnavailable / EvidenceSourcesUnavailable）は
        送出して呼び出し側が実行ごと中止する
      - 題材固有の失敗（画像が無い・台本が拒否された）は None を返して
        その題材だけ落とす
    """
    if cand["id"] in seen:
        print(f"- 見送り（すでに作成済み）: {cand['title'][:32]}")
        return None

    words = set(cand["keyword"].split())
    if any(len(words & used) >= SAME_TOPIC_OVERLAP for used in used_keywords):
        print(f"- 見送り（同じ出来事を最近すでに使用）: {cand['title'][:32]}")
        return None

    found = collect(cand["keyword"])
    if not found:
        print(f"- 見送り（根拠なし）: {cand['title'][:32]}")
        return None

    ev = next((e for e in found if e.source_url not in used_sources), None)
    if ev is None:
        print(f"- 見送り（同じ発言を最近すでに使用）: {cand['title'][:32]}")
        return None

    # 画像は台本生成の**前**に取る。後回しにすると、画像で失敗すると
    # 分かっている題材に Anthropic API の課金を使ってしまう（run_daily と同じ）。
    part_dir = workdir / f"seg{index}"
    photo = part_dir / "photo.jpg"
    license_path = part_dir / "license.json"
    if not (photo.exists() and license_path.exists()):
        try:
            license_rec = ensure_photo(ev, photo)
        except Exception as e:            # noqa: BLE001
            print(f"- 見送り（画像を取得できません）: {cand['title'][:32]} {e}")
            return None
        license_path.write_text(
            json.dumps(license_rec, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    recipe = build_recipe(cand, ev)
    RECIPES.mkdir(parents=True, exist_ok=True)
    (RECIPES / f"{cand['id']}.json").write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    try:
        script = write_segment(recipe)
    except ScriptGenerationRejected as e:
        print(f"! 台本生成がこの題材で失敗しました（この題材は飛ばします）: "
              f"{cand['id']} {e}")
        return None

    # 画面の引用カードに出る文字列が一次資料に由来することを、ここでも確かめる。
    # 描画の直前（build_long.compose_segment）でも同じ関門を通るが、ここで
    # 差し替えておかないと long.json と画面が食い違う（run_daily の
    # ensure_grounded_card と同じ理由）。
    excerpt = ground_excerpt(script.quote_excerpt, ev.quote)
    if excerpt != (script.quote_excerpt or "").strip():
        print(f"! 引用カードの文言が逐語引用に含まれていません。"
              f"モデルの出力を捨てて機械抽出に差し替えます"
              f"（{script.quote_excerpt[:30]!r} → {excerpt!r}）")

    return {
        "kind": "segment",
        "candidate_id": cand["id"],
        "headline": script.headline,
        "subtitle": script.subtitle,
        "narration": script.narration,
        "quote_excerpt": excerpt,
        "quote": ev.quote,
        "source": ev.context,
        "source_url": ev.source_url,
        "keywords": sorted(words),
        "photo": f"seg{index}/photo.jpg",
        "license": json.loads(license_path.read_text(encoding="utf-8")),
        "wav": f"seg{index}.wav",
    }


def _write_meta(workdir: Path, title: str, tags: list[str],
                parts: list[dict], durations: list[float]) -> None:
    (workdir / "meta.json").write_text(json.dumps({
        "id": workdir.name,
        "title": title[:100],
        "tags": tags,
        "category_id": "25",
        "expected_channel_id": CHANNEL_ID,
        "privacy_status": "private",
        "source_url": next(p["source_url"] for p in parts
                           if p["kind"] == "segment"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = chapters([p["headline"] for p in parts], durations)
    body = ["この動画で扱った論点（章）", *lines, "",
            "根拠にした一次資料（国会会議録）"]
    for i, part in enumerate([p for p in parts if p["kind"] == "segment"],
                             start=1):
        body += [f"{i}. {part['source']}", f"   {part['source_url']}"]
    body += ["", "画像の出典"]
    for part in parts:
        if part["kind"] == "segment":
            body.append(part["license"]["attribution"].splitlines()[0])

    (workdir / "description.txt").write_text(
        "\n".join(body) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", metavar="ID", action="append", default=[],
                    help="題材にする候補ID（3回指定する）")
    ap.add_argument("--keyword", metavar="検索語", action="append", default=[],
                    help="RSSを使わず検索語から題材にする（3回指定する）")
    ap.add_argument("--candidates", type=int, default=20, metavar="N",
                    help="RSSから取り直す候補の件数（既定20）")
    ap.add_argument("--days-ahead", type=int, default=0, metavar="N",
                    help="何日先の枠に載せるか")
    ap.add_argument("--dry-run", action="store_true",
                    help="動画までは作るが、YouTubeへのアップロードは行わない")
    a = ap.parse_args()

    topics = len(a.only) + len(a.keyword)
    if not (SEGMENTS_MIN <= topics <= SEGMENTS_MAX):
        ap.error(f"題材は {SEGMENTS_MIN}〜{SEGMENTS_MAX} 件を指定してください"
                 f"（--only / --keyword を合わせて {topics} 件でした）。"
                 "採用ゲートは見出しと引用の関連性を判定しないので、"
                 "題材は人が選ぶ必要があります")

    today = datetime.now(JST).date()
    slots = pending_slots(datetime.now(JST), a.days_ahead, kind="long")
    taken = taken_slots()
    slots = [s for s in slots if s not in taken]
    if not slots:
        print("空いている長尺の枠がありません（18:00は予約済みか、過ぎています）。"
              "--days-ahead 1 で翌日分を作れます")
        return
    slot = slots[0]
    print(f"- 対象の枠: {slot.strftime('%m/%d %H:%M')}")

    candidates = resolve_candidates(a.only, a.keyword, a.candidates)
    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))
               if SEEN.exists() else [])
    used_sources, used_keywords = load_used(today)
    if used_sources:
        print(f"- 直近{USED_LOOKBACK_DAYS}日で使った発言 {len(used_sources)}件を"
              "重複除外の対象にします")

    workdir = WORK / f"long-{make_id(' '.join(c['id'] for c in candidates))}"
    workdir.mkdir(parents=True, exist_ok=True)

    segments: list[dict] = []
    try:
        for cand in candidates:
            part = prepare_segment(cand, workdir, len(segments) + 1,
                                   used_sources, used_keywords, seen)
            if part is None:
                continue
            segments.append(part)
            used_sources.add(part["source_url"])
            used_keywords.append(set(part["keywords"]))
    except EvidenceSourcesUnavailable as e:
        print(f"✗ 一次資料の取得元に接続できませんでした。環境不備の可能性が"
              f"高いため中止します: {e}", file=sys.stderr)
        sys.exit(1)
    except ScriptWriterUnavailable as e:
        print(f"✗ 台本生成が失敗しました。ANTHROPIC_API_KEY が未設定／無効など、"
              f"環境不備の可能性が高いため中止します: {e}", file=sys.stderr)
        sys.exit(1)

    if len(segments) < SEGMENTS_MIN:
        print(f"✗ 使える題材が {len(segments)} 件しかありません"
              f"（{SEGMENTS_MIN}件以上必要）。題材を選び直してください",
              file=sys.stderr)
        sys.exit(1)

    headlines = [p["headline"] for p in segments]
    parts = [{"kind": "intro", "headline": INTRO_HEADLINE,
              "subtitle": INTRO_HEADLINE,
              "narration": intro_narration(headlines), "wav": "intro.wav"},
             *segments,
             {"kind": "outro", "headline": OUTRO_HEADLINE,
              "subtitle": OUTRO_HEADLINE,
              "narration": outro_narration(), "wav": "outro.wav"}]

    windows = {"intro": (INTRO_TARGET_MIN, INTRO_TARGET_MAX),
               "segment": (SEGMENT_TARGET_MIN, SEGMENT_TARGET_MAX),
               "outro": (OUTRO_TARGET_MIN, OUTRO_TARGET_MAX)}
    try:
        for part in parts:
            low, high = windows[part["kind"]]
            print(f"- 音声合成: {part['headline'][:24]}（{len(part['narration'])}字）")
            synthesize(part["narration"], workdir / part["wav"],
                       target_min=low, target_max=high)
    except Exception as e:                # noqa: BLE001
        print(f"✗ 音声合成が失敗しました。VOICEVOXが起動していないなど、"
              f"環境不備の可能性が高いため中止します: {e}", file=sys.stderr)
        sys.exit(1)

    (workdir / "long.json").write_text(
        json.dumps({"parts": parts}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    build(workdir)

    durations = [wav_duration_seconds(workdir / p["wav"]) for p in parts]
    try:
        meta = write_long_meta(headlines)
    except ScriptWriterUnavailable as e:
        print(f"✗ タイトルの生成が失敗しました: {e}", file=sys.stderr)
        sys.exit(1)
    _write_meta(workdir, meta.title, meta.tags, parts, durations)
    print(f"- タイトル: {meta.title}")

    if a.dry_run:
        print(f"✓ {workdir / 'video.mp4'}（--dry-run のためアップロードしません）")
        return

    try:
        subprocess.run([sys.executable, "scripts/upload_youtube.py",
                        str(workdir)], check=True, cwd=ROOT)
    except subprocess.CalledProcessError as e:
        if e.returncode == EXIT_CHANNEL_UNVERIFIED:
            print("✗ アップロード先のチャンネルを確認できませんでした"
                  "（token.json は消さないこと）", file=sys.stderr)
        elif e.returncode == EXIT_CHANNEL_MISMATCH:
            print("✗ アップロード先のチャンネルが指定と一致しません",
                  file=sys.stderr)
        sys.exit(1)

    # ここから先で失敗しても、動画は既に YouTube 上にある。既出に入れて
    # おかないと、同じ題材でもう1本アップロードされる（upload_youtube.py に
    # 重複防止は無い）。run_daily.py と同じ判断。
    seen.update(p["candidate_id"] for p in segments)
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    for part in segments:
        save_used(today, part["source_url"], set(part["keywords"]))

    if slot <= datetime.now(JST):
        print(f"! 枠 {slot.strftime('%H:%M')} を過ぎてしまったため予約せず "
              f"private のまま残します。手動で公開してください: "
              f"python scripts/upload_youtube.py {workdir} --publish")
        return

    subprocess.run([sys.executable, "scripts/upload_youtube.py", str(workdir),
                    "--schedule", slot.isoformat()], check=True, cwd=ROOT)
    print(f"✓ {meta.title[:40]}（{slot.strftime('%m/%d %H:%M')} 公開予約）")


if __name__ == "__main__":
    main()
