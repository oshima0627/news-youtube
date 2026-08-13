#!/usr/bin/env python3
"""採用ゲートを通った題材を、独立した評価者に採点させる診断CLI。

    python scripts/relevance_eval.py                  # recipes/ 全件
    python scripts/relevance_eval.py recipes/x.json   # 指定した題材だけ
    python scripts/relevance_eval.py --json           # 機械可読で出す

採用ゲート（`evidence.find_passage`）が判定しているのは「検索語が同じ文脈に
2語以上固まって現れるか」であり、**引用が見出しの出来事を裏付けているか**は
見ていない。この CLI はその1軸だけを、生成側とは独立に採点する。

**生成側と分ける4点**（`specs/evaluation-rubric.md` 参照）:
  1. モデルが違う（生成は claude-opus-5、採点は MODEL）
  2. プロンプトが違う（台本の指示を一切含めない）
  3. 渡すものが違う（見出しと逐語引用だけ。台本も公開タイトルも渡さない）
  4. 基準がファイルにある（RUBRIC を読んで渡す。ここには基準を書かない）

4 が重要で、基準をこのファイルにも書くと `specs/evaluation-rubric.md` と
二重管理になり、片方だけ直したときに採点が静かにずれる。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

# 日本語をそのまま出す。Windows のコンソール既定は cp932 なので、
# 再設定しないと採点理由も --help も全部化ける（run_daily.py と同じ処置）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "recipes"
RUBRIC = ROOT / "specs" / "evaluation-rubric.md"

# 生成側は claude-opus-5。**採点は別のモデルで行う。**
# 同じモデルに書かせて同じモデルに採点させると、生成時と同じ癖が採点にも乗る。
# 判定基準はルーブリックが持っているので、採点側は最上位モデルでなくてよい。
MODEL = "claude-sonnet-5"
MAX_TOKENS = 4000

# anthropic SDK は必要になってから読み込む（理由は script_writer.py の
# 同じ箇所を参照。import に実測20.3秒かかる）。tests が差し替えるので
# モジュール属性として持たせておく。
Anthropic = None

_AUTH_HINT = (
    "Anthropic API の認証情報を解決できませんでした。"
    "ANTHROPIC_API_KEY を設定するか、`ant auth login` でプロファイルを作成してください。"
)


class RelevanceEvalUnavailable(RuntimeError):
    """採点そのものが実行できない状態（SDK未導入・認証不備・ルーブリック欠落）。

    script_writer が環境不備と題材固有の失敗を例外の型で分けているのは、
    run_daily.py が無人実行の途中で「中止すべきか次へ進むべきか」を判断
    するため。この CLI は人が起動して結果を読むものなので、そこまでの
    区別は要らない — 失敗したら理由を出して止まればよい。
    """


class Verdict(BaseModel):
    event: str = Field(
        description="見出しが報じている出来事を1文で。「〜が〜した」の形にする")
    score: int = Field(description="ルーブリックに従った点数。1〜5の整数")
    reason: str = Field(
        description="その点にした理由。引用のどこを見て判断したかを含める。80文字以内")
    timing_ok: bool = Field(
        description="見出しの出来事と引用の時点が1年以上ずれていなければ true")
    lead_ok: bool = Field(
        description="引用の**先頭部分**が見出しと関係していれば true。"
                    "見出しに関係する箇所が引用の後半にしか無ければ false")


SYSTEM = """あなたはニュース解説動画の品質を採点する評価者です。
制作者とは独立した立場で、渡された基準だけに従って採点します。

守ること:
- 与えられた基準（ルーブリック）以外の観点で加点・減点しない。
- 「話題が近い」ことを「出来事を裏付けている」と混同しない。
- 迷ったら低い方の点にする。
"""


def load_rubric() -> str:
    """採点基準をファイルから読む。

    見つからないときに空文字で続けると、基準なしの採点が高い点を返して
    「合格した」ように見える。**防ぎたい失敗そのもの**なので例外にする。
    """
    if not RUBRIC.exists():
        raise RelevanceEvalUnavailable(
            f"採点基準が見つかりません: {RUBRIC}。"
            "specs/evaluation-rubric.md を用意してください")
    return RUBRIC.read_text(encoding="utf-8")


def build_prompt(recipe: dict, rubric: str) -> str:
    """採点用のプロンプトを組み立てる。

    渡すのは見出しと逐語引用だけ。`script.json` や公開タイトルは渡さない
    （公開タイトルは引用に寄せて作られているので、それを見てから採点すると
    「タイトルと引用は合っている」という別の判定になる）。
    """
    ev = recipe["evidence"]
    return "\n".join([
        "# 採点基準",
        "",
        rubric,
        "",
        "# 採点対象",
        "",
        f"見出し: {recipe['headline']}",
        f"逐語引用: 「{ev.get('quote', '')}」",
        "",
        "上の基準に従って採点してください。",
    ])


def _IMPORT_SDK():
    """anthropic から必要な名前を取り出す。差し替え点を1箇所にするための薄い関数。"""
    from anthropic import Anthropic as _Anthropic
    return _Anthropic


def _load_sdk() -> None:
    global Anthropic
    if Anthropic is not None:
        return
    try:
        Anthropic = _IMPORT_SDK()
    except ImportError as e:
        raise RelevanceEvalUnavailable(
            "anthropic SDK を読み込めませんでした。"
            "`pip install -r requirements.txt` で導入してください"
            f"（元のエラー: {e}）") from e


def judge(recipe: dict, rubric: str) -> Verdict:
    _load_sdk()
    try:
        response = Anthropic().messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": build_prompt(recipe, rubric)}],
            output_format=Verdict,
        )
    except TypeError as e:
        # 認証情報が何も解決できないと SDK はリクエスト構築時に TypeError を出す
        # （script_writer.py の同じ分岐を参照）。実装バグの TypeError まで
        # 握りつぶさないよう内容で見分ける。
        if "authentication" not in str(e).lower():
            raise
        raise RelevanceEvalUnavailable(f"{_AUTH_HINT}（元のエラー: {e}）") from e
    except Exception as e:                        # noqa: BLE001
        if type(e).__name__ == "AuthenticationError":
            raise RelevanceEvalUnavailable(f"{_AUTH_HINT}（元のエラー: {e}）") from e
        raise

    parsed = response.parsed_output
    if parsed is None:
        raise RelevanceEvalUnavailable(
            "採点結果を構造化出力として受け取れませんでした"
            f"（stop_reason={response.stop_reason}）")
    return parsed


def summarize(results: list[tuple[dict, Verdict]]) -> dict:
    """合否を判定する。基準は specs/evaluation-rubric.md「合格ライン」。

    - 1点が1件でもあれば不合格（クリティカル項目。平均点で買い戻せない）
    - 3点以下が全体の 1/3 を超えたら不合格
    """
    total = len(results)
    scores = [v.score for _, v in results]
    critical = [r["id"] for r, v in results if v.score <= 1]
    low = [s for s in scores if s <= 3]
    low_ratio = len(low) / total if total else 0.0
    return {
        "total": total,
        "score5": sum(1 for s in scores if s >= 5),
        "low": len(low),
        "low_ratio": low_ratio,
        "critical_ids": critical,
        "passed": not critical and low_ratio <= 1 / 3,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="見出しと一次資料の関連性を独立に採点する")
    ap.add_argument("recipes", nargs="*", type=Path,
                    help="採点する recipes/<id>.json。省略時は recipes/ 全件")
    ap.add_argument("--json", action="store_true", help="機械可読な JSON で出す")
    args = ap.parse_args(argv)

    paths = args.recipes or sorted(RECIPES.glob("*.json"))
    if not paths:
        print(f"✗ 採点対象がありません（{RECIPES} が空です）", file=sys.stderr)
        return 1

    # 環境不備は生のトレースバックではなく理由の1行にする。ログを読むときは
    # 「✗ 」で始まる行だけを追う運用（CLAUDE.md 参照）に合わせている。
    try:
        rubric = load_rubric()
        results: list[tuple[dict, Verdict]] = []
        for p in paths:
            recipe = json.loads(p.read_text(encoding="utf-8"))
            verdict = judge(recipe, rubric)
            results.append((recipe, verdict))
            if not args.json:
                flags = "".join([
                    "" if verdict.timing_ok else " [時点ずれ]",
                    "" if verdict.lead_ok else " [カード先頭]",
                ])
                print(f"{verdict.score}点 {recipe['id']} "
                      f"{recipe['headline'][:34]}{flags}")
                print(f"     出来事: {verdict.event}")
                print(f"     理由  : {verdict.reason}")
    except RelevanceEvalUnavailable as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    s = summarize(results)
    if args.json:
        print(json.dumps({
            "summary": s,
            "results": [{"id": r["id"], "headline": r["headline"], **v.model_dump()}
                        for r, v in results],
        }, ensure_ascii=False, indent=2))
    else:
        print()
        print(f"{'✓' if s['passed'] else '✗'} "
              f"5点 {s['score5']}/{s['total']}、"
              f"3点以下 {s['low']}/{s['total']}（{s['low_ratio']:.0%}）")
        if s["critical_ids"]:
            print(f"✗ 1点（報じられた出来事が無い）: {', '.join(s['critical_ids'])}")

    # 合格ラインを外したら非ゼロ。ゲートや配点を触った後に走らせて、
    # 終了コードで採否を決められるようにしてある。
    return 0 if s["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
