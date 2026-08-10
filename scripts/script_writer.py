#!/usr/bin/env python3
"""台本の生成。

**渡すのは一次資料の抜粋だけ。** RSSの記事本文もリンクも渡さない。
記事を言い換えると翻案になるうえ、YouTube の量産型判定にも近づく。
書かせるのは「ニュースの要約」ではなく「この数字/この発言をどう読むか」。
"""

from __future__ import annotations

from anthropic import Anthropic, AuthenticationError
from pydantic import BaseModel, Field

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

# Anthropic SDK の認証解決チェーンは
#   ANTHROPIC_API_KEY → ANTHROPIC_AUTH_TOKEN → `ant auth login` のプロファイル
#   → Workload Identity Federation
# の順。環境変数だけを事前チェックして弾くと、プロファイルで認証できる環境を
# 誤って拒否してしまう。そのため事前チェックはせず、SDK自身の解決結果が
# 「認証情報が無い」だったとき（messages.parse 実行時に TypeError で判明する）
# を捕まえて、毎朝の無人実行でも原因が読み取れるメッセージに変換する。
_AUTH_HINT = (
    "Anthropic API の認証情報を解決できませんでした。"
    "ANTHROPIC_API_KEY を設定するか、`ant auth login` でプロファイルを作成してください。"
)


class ScriptWriterUnavailable(RuntimeError):
    """台本生成そのものが実行できない状態（環境不備）。

    ANTHROPIC_API_KEY が未設定／無効など、この題材に限らずどの題材で
    呼んでも同じ理由で確実に失敗する状況を表す。呼び出し側（run_daily.py）
    はこれを日次実行全体の即時中止シグナルとして扱う。
    """


class ScriptGenerationRejected(RuntimeError):
    """個別の題材に対する台本生成が失敗した（環境は正常）。

    Anthropic の安全フィルタによる refusal や、構造化出力として受け取れ
    なかった場合など、その題材の内容に起因して起こる失敗を表す
    （政治ニュースを扱う以上、特定の題材だけで現実に起こりうる）。
    他の題材では成功する可能性があるため、呼び出し側はこの題材だけを
    飛ばして次に進む。
    """


SYSTEM = """あなたは日本の政治・外交ニュースを扱う解説チャンネルの構成作家です。
与えられた一次資料（国会会議録の逐語引用、または政府統計）だけを根拠に、
60秒のショート動画の台本を書きます。

守ること:
- 一次資料に書かれていない事実を足さない。推測を断定で書かない。
- ニュースの要約ではなく、その発言・その数字が何を意味するかの解説にする。
- 話し言葉。ナレーションとしてそのまま読める文章にする。
- 特定の個人や団体への誹謗中傷、断定的な違法行為の指摘は書かない。
"""


class Script(BaseModel):
    title: str = Field(description="YouTubeのタイトル。60文字以内。ハッシュタグは含めない")
    headline: str = Field(description="画面上部に出す見出し。20文字以内")
    narration: str = Field(description="読み上げる本文。350〜400字")
    figure_label: str = Field(description="数値カードの見出し。10文字以内")
    figure_value: str = Field(description="数値カードに大きく出す値。12文字以内")
    tags: list[str] = Field(description="YouTubeのタグ。3〜6個")


def build_prompt(recipe: dict) -> str:
    ev = recipe["evidence"]
    parts = [
        f"題材: {recipe['headline']}",
        "",
        "一次資料:",
        f"  種別: {ev['kind']}",
        f"  出典: {ev['source_url']}",
        f"  文脈: {ev['context']}",
    ]
    if ev.get("quote"):
        parts.append(f"  逐語引用: 「{ev['quote']}」")
    if ev.get("figure"):
        parts.append(f"  数値: {ev['figure']}")
    parts += [
        "",
        "この一次資料だけを根拠に、60秒（350〜400字）のナレーションを書いてください。",
        "figure_value には、視聴者が一目で分かる数字か短い言葉を入れてください。",
    ]
    return "\n".join(parts)


def write(recipe: dict) -> Script:
    try:
        client = Anthropic()
        response = client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": build_prompt(recipe)}],
            output_format=Script,
        )
    except AuthenticationError as e:
        # 鍵/トークンは解決できたが無効・失効している場合（APIが401を返した場合）。
        # どの題材で呼んでも同じ理由で失敗する環境不備なので ScriptWriterUnavailable。
        raise ScriptWriterUnavailable(f"{_AUTH_HINT}（元のエラー: {e}）") from e
    except TypeError as e:
        # 認証情報が何も解決できなかった場合、SDK はリクエスト構築時にこの
        # TypeError を出す（メッセージに "authentication" を含む）。それ以外の
        # TypeError（実装側のバグ等）まで握りつぶさないよう、内容で見分ける。
        # こちらも環境不備なので ScriptWriterUnavailable。
        if "authentication" not in str(e).lower():
            raise
        raise ScriptWriterUnavailable(f"{_AUTH_HINT}（元のエラー: {e}）") from e

    if response.stop_reason == "refusal":
        # Anthropic の安全フィルタによる拒否。政治ニュースを扱う以上、
        # 特定の題材の内容（誰かの発言・行為への言及など）が理由で起こりうる。
        # 環境は正常で、他の題材なら成功する可能性があるので
        # ScriptGenerationRejected（この題材だけ飛ばす対象）にする。
        raise ScriptGenerationRejected(f"台本生成が拒否されました: {response.stop_details}")
    parsed = response.parsed_output
    if parsed is None:
        # refusal と同様、この呼び出し・この題材固有の失敗（max_tokens到達や
        # 構造化出力パース失敗など）であり、環境不備ではない。
        raise ScriptGenerationRejected(
            "台本を構造化出力として受け取れませんでした"
            f"（stop_reason={response.stop_reason}, "
            f"usage={getattr(response, 'usage', None)}）"
        )
    return parsed
