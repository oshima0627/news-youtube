#!/usr/bin/env python3
"""台本の生成。

**渡すのは一次資料の抜粋だけ。** RSSの記事本文もリンクも渡さない。
記事を言い換えると翻案になるうえ、YouTube の量産型判定にも近づく。
書かせるのは「ニュースの要約」ではなく「この数字/この発言をどう読むか」。
"""

from __future__ import annotations

from anthropic import Anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

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
    # ANTHROPIC_API_KEY が無い/空だと Anthropic() の内部で分かりにくい例外になるため、
    # 毎朝の自動実行で原因がすぐ読み取れるよう、ここで早期に落とす。
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY が設定されていません。台本生成をスキップします。"
            "（環境変数を設定してから再実行してください）"
        )

    client = Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": build_prompt(recipe)}],
        output_format=Script,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"台本生成が拒否されました: {response.stop_details}")
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("台本を構造化出力として受け取れませんでした")
    return parsed
