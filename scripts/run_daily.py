#!/usr/bin/env python3
"""1日分を作って予約公開まで通す。

  python scripts/run_daily.py
  python scripts/run_daily.py --dry-run   # アップロードだけ飛ばす

1回の実行で、当日のまだ来ていない枠の数だけ作り、YouTube側の予約公開に
載せて終わる。PCが日中落ちていても定刻に公開される。

手で起動する運用を前提にしている（タスクスケジューラに登録してもよいが、
必須ではない）。画像は発言者から自動で取るので、事前準備は要らない。
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
    # 環境不備での中止メッセージは stderr に出す。既定の Windows ロケール
    # （cp932）のままだと日本語の原因メッセージが文字化けし、「原因が明確に
    # 出る」という本タスクの目的そのものを損なうため、stdout と同様に
    # reconfigure する。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

WORK = ROOT / "work"
RECIPES = ROOT / "recipes"
CANDIDATES = WORK / "candidates.json"
SEEN = ROOT / "state" / "seen.json"
USED = ROOT / "state" / "used.json"
STREAK = ROOT / "state" / "empty_streak.json"
PUBLISHED = ROOT / "state" / "published.json"
CHANNEL_ID = "UCYHTfHJOoETzvpx-VZlUTng"

# 投稿枠も予約公開も JST 運用（slots.py / unpublish.py と同じ）。ローカル時刻
# （naive）で枠を計算しながら "+09:00" を文字列で直書きしていると、実行環境の
# タイムゾーンが JST でない瞬間（CI・タイムゾーン設定を変えた端末）に、
# 「まだ未来」と判定した枠に実際は過去の時刻を渡すことになり、YouTube 側に
# 拒否されて private のまま取り残される。タイムゾーンは1箇所で明示する。
JST = timezone(timedelta(hours=9))

from scripts.build_short import build  # noqa: E402
from scripts.collect_news import EXIT_NO_TOPIC  # noqa: E402
from scripts.commons import credit as commons_credit  # noqa: E402
from scripts.commons import resolve as resolve_photo  # noqa: E402
from scripts.evidence import (  # noqa: E402
    QUOTE_EXCERPT_MAX_CHARS,  # noqa: F401  （tests から run_daily 経由で参照）
    EvidenceSourcesUnavailable,
    build_recipe,
    collect,
    ground_excerpt,
)
from scripts.narrate import synthesize  # noqa: E402
from scripts.photos import download as download_photo  # noqa: E402
from scripts.script_writer import (  # noqa: E402
    ScriptGenerationRejected,
    ScriptWriterUnavailable,
    write,
)
from scripts.slots import pending_slots  # noqa: E402
from scripts.upload_youtube import EXIT_CHANNEL_MISMATCH  # noqa: E402

# 一次資料の取得元が「落ちている」と判断するまでの連続失敗数。
# evidence.collect() の EvidenceSourcesUnavailable は、系統が国会会議録の
# 1つしか無い今「1回の HTTP 失敗」でも送出されうる（search_speeches 側で
# リトライはするが、それでも抜けきらない一過性の失敗はある）。1件目で即中止
# すると、5xx が1回混ざっただけでその日が0本になる。逆に全候補ぶん見送りを
# 続けると環境不備に気づけない。連続で N 件失敗したときだけ中止に格上げする。
EVIDENCE_FAILURE_LIMIT = 3

# 検索語がこの数だけ重なっていたら「同じ出来事」とみなす。検索語は
# keywords.extract が返す2〜3語なので、2語一致はほぼ同じ題材を意味する。
SAME_TOPIC_OVERLAP = 2

# 重複判定をさかのぼる日数。seen.json は見出しのハッシュしか持たないので、
# 同じ出来事が翌日に別の見出しで流れてくると素通りする。実際、初日に公開した
# 「消費税減税」の題材が、翌日分でも**同じ発言（同じ出典URL）**を根拠に
# もう1本作られた。日をまたいで覚えておく必要がある。
USED_LOOKBACK_DAYS = 14


def load_used(today) -> tuple[set[str], list[set[str]]]:
    """直近に使った発言のURLと検索語を読む。(出典URL, 検索語の集合の並び)"""
    if not USED.exists():
        return set(), []
    entries = json.loads(USED.read_text(encoding="utf-8"))
    limit = (today - timedelta(days=USED_LOOKBACK_DAYS)).isoformat()
    recent = [e for e in entries if e.get("date", "") >= limit]
    return ({e["source_url"] for e in recent},
            [set(e.get("keywords") or []) for e in recent])


def save_used(today, source_url: str, keywords: set[str]) -> None:
    """使った発言を記録する。古いものは落とす。"""
    entries = (json.loads(USED.read_text(encoding="utf-8"))
               if USED.exists() else [])
    limit = (today - timedelta(days=USED_LOOKBACK_DAYS)).isoformat()
    entries = [e for e in entries if e.get("date", "") >= limit]
    entries.append({"date": today.isoformat(), "source_url": source_url,
                    "keywords": sorted(keywords)})
    USED.parent.mkdir(parents=True, exist_ok=True)
    USED.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def taken_slots() -> set[datetime]:
    """すでに予約が入っている枠（JST）。

    枠は pending_slots が「まだ来ていない時刻」だけで決めていて、その枠が
    **すでに埋まっているか**を見ていなかった。--days-ahead で先の日付ぶんを
    作り置きすると、その日が来たときの定例実行が同じ枠にもう1本アップロード
    してしまう（upload_youtube.py に重複防止は無いので、同じ時刻に2本並ぶ）。

    予約を外した動画（unpublish.py）は publish_at を落とすので、ここには
    出てこない＝枠が空いたものとして扱われる。
    """
    if not PUBLISHED.exists():
        return set()
    try:
        data = json.loads(PUBLISHED.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        # 「予約済みは無い」と見なして進むと、埋まっている枠にもう1本載せる。
        # 重複投稿を防ぐための情報なので、読めないなら止める。
        print(f"✗ {PUBLISHED} が壊れています（JSONとして読めません）。"
              f"どの枠が埋まっているか分からないまま実行すると同じ枠に"
              f"2本目を載せてしまうため中止します: {e}", file=sys.stderr)
        sys.exit(1)

    out: set[datetime] = set()
    for key, v in (data.get("videos") or {}).items():
        publish_at = v.get("publish_at")
        if not publish_at:
            continue
        try:
            dt = datetime.fromisoformat(publish_at)
        except ValueError:
            # 黙って無視すると、その枠が空いていることにして2本目を載せる。
            # unpublish.py の同じ判断（必ず警告する）に合わせる。
            print(f"! publish_at をパースできません（枠の判定から除きます）: "
                  f"{key} publish_at={publish_at!r}")
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        out.add(dt.astimezone(JST))
    return out


def _bump_empty_streak(made: int) -> None:
    """0本の日が続いたら警告する。収益化要件は90日で3本以上。"""
    n = 0 if made else (json.loads(STREAK.read_text(encoding="utf-8"))["days"]
                        if STREAK.exists() else 0) + 1
    STREAK.parent.mkdir(parents=True, exist_ok=True)
    STREAK.write_text(json.dumps({"days": n}) + "\n", encoding="utf-8")
    if n >= 3:
        print(f"! {n}日続けて0本です。RSSの配点か採用ゲートを見直してください")


def ensure_photo(ev, dest: Path) -> dict:
    """発言者から画像を決めて落とし、license.json 用の記録を返す。

    取得元は commons.resolve が決める（発言者の ja.wikipedia 記事画像 →
    取れなければ国会議事堂）。ダウンロードは photos.download を通すので、
    ホスト（upload.wikimedia.org）のホワイトリスト検証がもう一度かかる。
    見つからなければ例外を送出し、呼び出し側がこの題材だけ飛ばす。
    """
    info = resolve_photo(ev.speaker)
    if not info:
        raise RuntimeError(
            f"使える画像が見つかりませんでした（発言者: {ev.speaker or '不明'}）")
    who = "汎用画像" if info.get("is_fallback") else f"{info['article']} の記事画像"
    print(f"  画像: {who}（{info['license_name']}）")
    return download_photo(info["url"], dest, credit=commons_credit(info))


def ensure_grounded_card(script, evidence: dict):
    """画面の根拠カードに出る文字列が一次資料に由来することを保証する。

    判定そのものは `evidence.ground_excerpt`。同じ検証を build_short 側でも
    描画の直前に通している（手でCLIを叩く経路がここを通らないため）。
    ここに残しているのは、**差し替えを script.json に残す**ためで、
    画面と script.json が食い違わないようにしている。

    根拠カードには必ず一次資料の出典キャプション（会議名・日付・発言者）が
    印字される。したがってカードに出す文字列が一次資料に無い言葉だと、
    **モデルが作った文字列に一次資料の出典が付く**ことになり、
    「一次資料が取れなければ公開しない」という設計方針がそこだけ破れる。

    - `evidence["figure"]`（一次資料が持っている実際の数値）が空でないとき
      は従来どおり数値カードを使う。値は一次資料由来なので検証は不要。
    - 空のとき（＝発言系。現状の唯一の系統である国会会議録は常にこちら）は
      引用カードを使う。画面に出るのは `script.quote_excerpt` なので、
      それが `evidence["quote"]` の**部分文字列**であることをここで確認する。
      外れていたらモデルの出力を捨て、逐語引用の先頭から機械的に抜き出した
      文字列に差し替える（捏造をそのまま公開しない）。

    戻り値は検証済みの Script（差し替えが起きた場合は新しいインスタンス）。
    """
    if (evidence.get("figure") or "").strip():
        return script

    excerpt = (script.quote_excerpt or "").strip()
    fallback = ground_excerpt(excerpt, evidence.get("quote") or "")
    if fallback == excerpt:
        return script

    print(f"! 引用カードの文言が一次資料の逐語引用に含まれていません。"
          f"モデルの出力を捨てて逐語引用の先頭から機械的に抜き出します"
          f"（モデル出力: {excerpt[:40]!r} → 差し替え: {fallback!r}）")
    return script.model_copy(update={"quote_excerpt": fallback})


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
    ap.add_argument("--days-ahead", type=int, default=0, metavar="N",
                    help="何日先の枠に載せるか（1で翌日の朝・夕の2枠）")
    ap.add_argument("--limit", type=int, default=None, metavar="N",
                    help="先頭からN枠だけ埋める（1枠ぶんだけ作り直したいとき）")
    a = ap.parse_args()
    if a.limit is not None and a.limit < 1:
        # 黙って通すと slots が空になり、「対象の枠は過ぎています」という
        # 実際とは違う理由を表示して終わる。
        ap.error("--limit は1以上を指定してください")

    slots = pending_slots(datetime.now(JST), a.days_ahead)

    # すでに予約が入っている枠は外す（詳細は taken_slots）。
    taken = taken_slots()
    if taken:
        filled = [s for s in slots if s in taken]
        if filled:
            print(f"- 予約済みのため対象外: "
                  f"{[s.strftime('%m/%d %H:%M') for s in filled]}")
        slots = [s for s in slots if s not in taken]
        if not slots:
            # 「題材が無かった日」ではないので empty_streak には数えない。
            print("空いている枠がありません（すべて予約済み）")
            return

    if a.limit is not None:
        # 公開前に1本だけ差し替えたいとき、--days-ahead だけではその日の
        # **残り全部**を作ってしまい、すでに予約済みの枠に2本目が重なる
        # （upload_youtube.py に重複防止が無いので、同じ時刻に2本並ぶ）。
        slots = slots[:a.limit]
    if not slots:
        print("対象の枠は過ぎています。--days-ahead 1 で翌日分を作れます")
        return
    print(f"- 本日の残り枠: {[s.strftime('%H:%M') for s in slots]}")

    # collect_news.py は「全フィードが失敗」「候補0件」を非0終了で知らせる
    # （evidence.collect() の EvidenceSourcesUnavailable と同じ扱い）。
    # ここで握りつぶすと、ネットワークが落ちている日に候補0件のまま
    # 「本日 0/2 本」と表示して終了コード0で終わり、原因に気づけない。
    try:
        subprocess.run([sys.executable, "scripts/collect_news.py",
                        "--limit", "20"], check=True, cwd=ROOT)
    except subprocess.CalledProcessError as e:
        # EXIT_NO_TOPIC は「フィードは取れたが、国会で議論されえない題材
        # （天気・スポーツ）と既出を除いたら何も残らなかった」。環境は
        # 正常なので中止せず、0本の日として静かに終える。
        if e.returncode == EXIT_NO_TOPIC:
            print("本日 0/{} 本（採れる題材がありませんでした）".format(len(slots)))
            _bump_empty_streak(0)
            return
        print(f"✗ 候補の収集に失敗しました。RSSの取得元に接続できないなど"
              f"環境不備の可能性が高いため日次実行を中止します"
              f"（終了コード {e.returncode}）", file=sys.stderr)
        sys.exit(1)

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    if not candidates:
        # collect_news.py 側でも弾いているが、work/candidates.json を手で
        # 用意する運用もあるので入口側でも確認する。
        print(f"✗ 候補が1件もありません（{CANDIDATES}）。"
              "RSSの取得か seen.json による除外を確認してください",
              file=sys.stderr)
        sys.exit(1)

    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))
               if SEEN.exists() else [])
    made = 0
    aborted = False
    evidence_failures = 0        # 連続して EvidenceSourcesUnavailable になった数
    evidence_ok = False          # 一度でも一次資料の取得に成功したか
    # 同じ発言を根拠にした動画を2本作らないための記録。RSSには同じ出来事の
    # 見出しが各社から並ぶ（「消費税減税 基本方針決定」と「食料品の消費税減税
    # 5日にも閣議決定」など）ため、素通しにすると朝と夕方でほぼ同じ内容の
    # 動画が並び、まさに量産型と見なされる。
    #
    # **直近 USED_LOOKBACK_DAYS 日ぶんを読み込んでから始める。** 実行中だけの
    # 記録にしていたため、初日に公開した題材が翌日分でも同じ発言を根拠に
    # もう1本作られた（出典URLまで同一だった）。
    today = datetime.now(JST).date()
    used_sources, used_keywords = load_used(today)
    if used_sources:
        print(f"- 直近{USED_LOOKBACK_DAYS}日で使った発言 {len(used_sources)}件を"
              "重複除外の対象にします")

    try:
        for cand in candidates:
            if made >= len(slots):
                break

            # 一次資料の取得元（国会会議録API等）が1系統も応答しない状況は
            # 「根拠が無かった」（正常系、空リスト）とは違う環境不備。
            # evidence.collect() がその2つを EvidenceSourcesUnavailable の
            # 有無で区別しているので、ここでも区別する。区別しないと、
            # APIが疎通不能なだけの日に全候補ぶん「見送り（根拠なし）」を
            # 繰り返した末、終了コード0で「本日 0/2 本」とだけ表示されて
            # 原因に気づけない（write/synthesize と同じ理由で中止する）。
            #
            # ただし1件目で即中止はしない。系統が国会会議録の1つしか無い今、
            # 「1回タイムアウトした」がそのまま「全系統ダウン」になるため、
            # 5xx が1回混ざっただけでその日が0本＋exit 1 になってしまう
            # （search_speeches 側でもリトライしている）。連続 N 件失敗した
            # ときだけ「本当に落ちている」と判断して中止に格上げする。
            words = set(cand["keyword"].split())
            if any(len(words & used) >= SAME_TOPIC_OVERLAP
                   for used in used_keywords):
                print(f"- 見送り（同じ出来事を最近すでに使用）: "
                      f"{cand['title'][:32]}")
                continue

            try:
                found = collect(cand["keyword"])
            except EvidenceSourcesUnavailable as e:
                evidence_failures += 1
                print(f"! 一次資料の取得に失敗しました"
                      f"（連続 {evidence_failures}/{EVIDENCE_FAILURE_LIMIT} 件目）: {e}")
                if evidence_failures >= EVIDENCE_FAILURE_LIMIT:
                    print(f"✗ 一次資料の取得元に{evidence_failures}件連続で"
                          f"接続できませんでした。環境不備の可能性が高いため"
                          f"日次実行を中止します: {e}", file=sys.stderr)
                    aborted = True
                    break
                continue
            evidence_failures = 0
            evidence_ok = True
            if not found:
                print(f"- 見送り（根拠なし）: {cand['title'][:32]}")
                continue

            # found は関連性の高い順。当日すでに使った発言は飛ばして次点を採る。
            ev = next((e for e in found if e.source_url not in used_sources), None)
            if ev is None:
                print(f"- 見送り（同じ発言を最近すでに使用）: "
                      f"{cand['title'][:32]}")
                continue

            workdir = WORK / cand["id"]

            # 画像は発言者から自動で決める（ja.wikipedia の記事画像 →
            # 取れなければ国会議事堂）。台本生成・音声合成の**前**に取りに行く。
            # 後回しにすると、画像で失敗すると分かっている題材に Anthropic API
            # の課金と VOICEVOX の時間を使ってしまう。
            # 手で用意した画像があるときはそれを尊重する（fetch_photo.py で
            # 差し替えた1枚を、翌日の実行が黙って上書きしないため）。
            photo = workdir / "photo.jpg"
            license_path = workdir / "license.json"
            if not (photo.exists() and license_path.exists()):
                try:
                    license_rec = ensure_photo(ev, photo)
                except Exception as e:            # noqa: BLE001
                    print(f"- 見送り（画像を取得できません）: "
                          f"{cand['id']} {cand['title'][:32]} {e}")
                    continue
                license_path.write_text(
                    json.dumps(license_rec, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")

            # レシピの書き出しは画像チェックより**後ろ**に置く。前に置くと、
            # 画像が用意されず一度も動画にならなかった題材のレシピが
            # recipes/ に溜まり続ける（recipes/ は「再現の単位」であって
            # 「検討した候補の記録」ではない）。
            recipe = build_recipe(cand, ev)
            RECIPES.mkdir(parents=True, exist_ok=True)
            (RECIPES / f"{cand['id']}.json").write_text(
                json.dumps(recipe, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")

            # write() は失敗の原因によって例外型が分かれている
            # （scripts/script_writer.py 参照）:
            #   - ScriptWriterUnavailable: ANTHROPIC_API_KEY 未設定／無効など
            #     の環境不備。どの題材で呼んでも同じ理由で確実に失敗するため、
            #     題材を飛ばさず日次実行全体をその場で中止する。
            #   - ScriptGenerationRejected: Anthropic の安全フィルタによる
            #     refusal や構造化出力の失敗など、この題材の内容固有の失敗。
            #     政治ニュースを扱う以上、特定の題材だけで現実に起こりうる。
            #     環境は正常で他の題材なら成功しうるので、この題材だけ飛ばして
            #     次に進む（日次実行全体は止めない）。
            try:
                script = write(recipe)
            except ScriptWriterUnavailable as e:
                print(f"✗ 台本生成が失敗しました。ANTHROPIC_API_KEY が未設定／"
                      f"無効など、環境不備の可能性が高いため日次実行を"
                      f"中止します: {e}", file=sys.stderr)
                aborted = True
                break
            except ScriptGenerationRejected as e:
                print(f"! 台本生成がこの題材で失敗しました"
                      f"（この題材は飛ばします）: {cand['id']} {e}")
                continue

            # synthesize() は VOICEVOX の接続確認（ensure_engine）に失敗した
            # ときだけ例外を投げる設計になっている（尺のズレ等は例外にせず
            # 警告に留める）。したがってここに来る失敗はほぼ確実に環境不備
            # （VOICEVOX未起動）であり、write() の環境不備側と同じ扱いにする。
            try:
                synthesize(script.narration, workdir / "voice.wav")
            except Exception as e:                # noqa: BLE001
                print(f"✗ 音声合成が失敗しました。VOICEVOXが起動していない"
                      f"など、環境不備の可能性が高いため日次実行を中止します: "
                      f"{e}", file=sys.stderr)
                aborted = True
                break

            # 画面の根拠カードに出る文字列が一次資料に由来することを、
            # script.json を書き出す前に保証する（詳細は ensure_grounded_card）。
            script = ensure_grounded_card(script, recipe["evidence"])

            # ここから先（動画合成・アップロード）は画像やffmpeg、YouTube側の
            # 一時的なエラーなど題材固有の要因で失敗しうる。1本の失敗で当日を
            # 全部落とさない。work/ は残るので次回リトライできる
            stuck_private = False
            # 1回目（private アップロード）が成功したかどうか。2回目
            # （--schedule）だけが落ちた場合、動画は既に YouTube 上にあるので
            # 既出にしないと翌日また同じ題材を作って**もう1本**上げてしまう
            # （upload_youtube.py に重複防止が無い）。stuck_private と同じ理由。
            uploaded = False
            try:
                license_ = json.loads(license_path.read_text(encoding="utf-8"))
                (workdir / "script.json").write_text(
                    script.model_dump_json(indent=2) + "\n", encoding="utf-8")
                _write_meta(workdir, script, license_, recipe["evidence"])
                build(workdir)

                if not a.dry_run:
                    subprocess.run([sys.executable, "scripts/upload_youtube.py",
                                    str(workdir)], check=True, cwd=ROOT)
                    uploaded = True

                    # slots はループ開始時に一度だけ計算している。収集〜台本
                    # 〜音声合成〜動画合成〜アップロードには数分かかりうるので、
                    # 18:30直前に起動したときなど、ここに来た時点で対象の枠が
                    # すでに過去になっているおそれがある。過去時刻を
                    # --schedule に渡すと YouTube 側に拒否され、動画は
                    # private のまま残ってしまう。渡す直前に改めて確認する。
                    slot = slots[made]
                    if slot <= datetime.now(JST):
                        stuck_private = True
                        print(f"! 枠 {slot.strftime('%H:%M')} を過ぎてしまった"
                              "ため予約せず private のまま残します。"
                              "手動で確認して公開してください: "
                              f"python scripts/upload_youtube.py {workdir} "
                              "--publish")
                    else:
                        subprocess.run(
                            [sys.executable, "scripts/upload_youtube.py",
                             str(workdir), "--schedule", slot.isoformat()],
                            check=True, cwd=ROOT)
            except Exception as e:                # noqa: BLE001
                # アップロード済みなら、失敗しても既出に入れる。入れないと
                # 翌日また同じ題材を処理し、同じ動画がもう1本 YouTube に並ぶ。
                if uploaded and not a.dry_run:
                    seen.add(cand["id"])
                    print(f"! アップロード自体は成功しています。重複投稿を"
                          f"避けるため既出に入れます（YouTube Studio で "
                          f"private のまま残っていないか確認してください）: "
                          f"{cand['id']}")

                # チャンネル取り違えガード（upload_youtube.py の
                # assert_expected_channel）が発動したときは専用の終了コードで
                # 返ってくる。token.json が別チャンネルに紐づいている環境不備
                # なので、どの題材でも同じ理由で必ず失敗する。題材固有の失敗と
                # して次に進むと、全候補ぶん同じ失敗を繰り返した末に
                # 終了コード0で「本日 0/2 本」とだけ表示されて気づけない。
                if (isinstance(e, subprocess.CalledProcessError)
                        and e.returncode == EXIT_CHANNEL_MISMATCH):
                    print(f"✗ アップロード先のチャンネルが指定と一致しません"
                          f"（{cand['id']}）。token.json が別チャンネルに"
                          f"紐づいている可能性が高いため日次実行を中止します。"
                          f"token.json を削除し "
                          f"python scripts/upload_youtube.py --auth-only で"
                          f"正しいチャンネルを選び直してください",
                          file=sys.stderr)
                    aborted = True
                    break

                print(f"! 失敗しました（この題材は飛ばします）: {cand['id']} {e}")
                continue

            # --dry-run のときはアップロードしていないので既出にしない。
            # ここで既出にしてしまうと、本番実行（--dry-run無し）のときに
            # この題材が二度と拾われず、結局その日は無投稿のまま終わる。
            #
            # 予約時刻を過ぎて private のまま残った場合（stuck_private）は
            # --dry-run ではないので既出に入れる。動画自体は既にアップロード
            # 済みであり、既出に入れずに次回また同じ候補を処理すると、
            # write()/synthesize()/build() をやり直した上で
            # upload_youtube.py がもう1本アップロードしてしまう
            # （upload_youtube.py に重複防止や更新の仕組みが無いため）。
            # 「同じ内容の動画が2本並ぶ」事故より、「1本が private のまま
            # 手動公開待ちになる」ほうが実害が小さいので、既出に入れる方を選ぶ。
            if not a.dry_run:
                seen.add(cand["id"])
            used_sources.add(ev.source_url)
            used_keywords.append(words)
            if not a.dry_run:
                save_used(today, ev.source_url, words)
            made += 1
            mark = "（要手動公開）" if stuck_private else ""
            print(f"✓ {made}/{len(slots)} {script.title[:40]}{mark}")
    finally:
        # 中止した場合でも、そこまでに投稿できた分は既出として残す
        SEEN.parent.mkdir(parents=True, exist_ok=True)
        SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    # 候補を全部試しても一次資料の取得に一度も成功しなかった場合も環境不備扱い。
    # EVIDENCE_FAILURE_LIMIT に届く前に候補が尽きるケース（候補が2件しか無い
    # 日など）を、静かな「本日 0/2 本」で終わらせないため。
    if not aborted and not evidence_ok and evidence_failures:
        print(f"✗ 一次資料の取得が全候補（{evidence_failures}件）で失敗しました。"
              "環境不備の可能性が高いため異常終了します", file=sys.stderr)
        aborted = True

    print(f"本日 {made}/{len(slots)} 本")
    if aborted:
        sys.exit(1)
    # 環境不備での中断は「題材が無い」わけではないので streak には数えない
    _bump_empty_streak(made)


if __name__ == "__main__":
    main()
