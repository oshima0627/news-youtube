#!/usr/bin/env python3
"""台本の生成。

**渡すのは一次資料の抜粋だけ。** RSSの記事本文もリンクも渡さない。
記事を言い換えると翻案になるうえ、YouTube の量産型判定にも近づく。
書かせるのは「ニュースの要約」ではなく「この数字/この発言をどう読むか」。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# anthropic SDK は**必要になってから**読み込む。import に実測20.3秒かかり
# （`python -X importtime` で確認）、run_daily.py はモジュール先頭で
# script_writer を import するため、台本生成に到達しない日— 枠が全部
# 埋まっていて何もせず終わる日— でもこの20秒を払っていた。
#
# 遅延させても失敗の型は変えない（_load_sdk 参照）。tests はここを
# 差し替えるので、モジュール属性として持たせておく必要がある。
Anthropic = None
AuthenticationError: type[BaseException] | tuple = ()   # 読み込み前は決して一致しない

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


# 秒/字は合成側の実測値なので narrate に置いてある（1箇所で持つ）。
# 字数指定はこの値を通して narrate の許容範囲（TARGET_MIN/TARGET_MAX）に
# 収まるようにする（tests/test_script_writer.py が両者を縛っている）。
#
# もとは 350〜400字。実測では350字でも62.25秒あり、**どの本数でも必ず**
# 56〜61秒を外していた。0.171秒/字で 56.4〜60.7秒になる範囲に寄せてある。
#
# ただしこれは「そのまま読んでちょうど60秒になる長さを頼む」だけで、
# **尺を保証するものではない**。実測では締めた後も2本中1本が378字で返った。
# 尺そのものは narrate 側が字数から speedScale を見積もって合わせる。
NARRATION_MIN_CHARS = 330
NARRATION_MAX_CHARS = 355

NARRATION_SPAN = f"{NARRATION_MIN_CHARS}〜{NARRATION_MAX_CHARS}字"


class Script(BaseModel):
    title: str = Field(description="YouTubeのタイトル。60文字以内。ハッシュタグは含めない")
    headline: str = Field(description="画面上部に出す見出し。20文字以内")
    narration: str = Field(description=f"読み上げる本文。{NARRATION_SPAN}")
    subtitle: str = Field(
        description="字幕バンドに出す要点。40文字以内")
    quote_excerpt: str = Field(
        description="一次資料の逐語引用からそのまま抜き出した短い一節。"
                    "25文字以内。言い換えないこと")
    # figure_label / figure_value は、一次資料が実際の数値を持つ系統
    # （e-Stat の getStatsData など）が戻ったときに数値カードで使う。
    # 現状の唯一の系統（国会会議録）は Evidence.figure が常に空なので、
    # 画面には quote_excerpt を使った引用カードが出る（cards.py 参照）。
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
        f"この一次資料だけを根拠に、60秒（{NARRATION_SPAN}）のナレーションを"
        "書いてください。",
        "subtitle には、字幕バンドに出す要点を40文字以内で書いてください"
        "（ナレーション全文ではありません）。",
    ]
    if ev.get("quote"):
        # 画面に出るのはこの一節そのもの（引用カード）。言い換えると、
        # 一次資料の出典キャプションが付いた文字列が一次資料と一致しなくなる。
        # run_daily.py は逐語引用の部分文字列であることを実際に検証し、
        # 外れていたら機械抽出で差し替える。
        parts.append(
            "quote_excerpt には、上の逐語引用から**そのまま**（1文字も変えずに）"
            "抜き出した25文字以内の一節を入れてください。要約・言い換えは禁止です。")
    if ev.get("figure"):
        parts.append(
            "figure_label / figure_value には、上の数値を視聴者が一目で分かる形で"
            "入れてください。")
    return "\n".join(parts)


def _IMPORT_SDK():
    """anthropic から必要な名前を取り出す。差し替え点を1箇所にするための薄い関数。"""
    from anthropic import Anthropic as _Anthropic
    from anthropic import AuthenticationError as _AuthenticationError
    return _Anthropic, _AuthenticationError


def _load_sdk() -> None:
    """anthropic SDK を必要になってから読み込む。

    読み込めないときは **ScriptWriterUnavailable にして送出する。**
    素の ImportError のまま出すと、run_daily.py の「ScriptWriterUnavailable
    なら日次実行を即座に中止」の分岐に乗らず、題材固有の失敗とも区別されない
    まま素のスタックトレースが出るだけになる。遅延 import にしたせいで
    失敗の型が変わってはいけない。
    """
    global Anthropic, AuthenticationError
    if Anthropic is not None:
        return
    try:
        Anthropic, AuthenticationError = _IMPORT_SDK()
    except ImportError as e:
        raise ScriptWriterUnavailable(
            "anthropic SDK を読み込めませんでした。"
            "`pip install -r requirements.txt` で導入してください"
            f"（元のエラー: {e}）") from e


def write(recipe: dict) -> Script:
    _load_sdk()
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
