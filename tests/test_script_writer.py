import subprocess
import sys
from pathlib import Path

import pytest

from scripts import narrate, script_writer
from scripts.script_writer import (
    Script,
    ScriptGenerationRejected,
    ScriptWriterUnavailable,
    build_prompt,
    write,
)

RECIPE = {
    "id": "abc123",
    "headline": "野田代表が議員定数削減で発言",
    "keyword": "議員定数 削減",
    "category": "政治",
    "evidence": {
        "kind": "speech",
        "source_url": "https://kokkai.ndl.go.jp/#/detail?x=1",
        "figure": "",
        "quote": "私どもは議員定数を四十五削減すると申し上げてまいりました。",
        "context": "第217回国会 衆議院予算委員会 2025-11-20 野田佳彦",
    },
}


def test_一次資料の引用と出典がプロンプトに入る():
    got = build_prompt(RECIPE)
    assert "私どもは議員定数を四十五削減する" in got
    assert "kokkai.ndl.go.jp" in got
    assert "第217回国会" in got


def test_RSSのリンクはプロンプトに渡さない():
    # 記事本文を渡すと翻案になる。渡すのは一次資料だけ
    recipe = dict(RECIPE, link="https://www3.nhk.or.jp/news/html/1.html")
    assert "nhk.or.jp" not in build_prompt(recipe)


def test_尺の指示が入る():
    got = build_prompt(RECIPE)
    span = f"{script_writer.NARRATION_MIN_CHARS}〜{script_writer.NARRATION_MAX_CHARS}字"
    assert span in got


def test_ナレーションの字数指定は尺の許容範囲に収まる():
    """台本の字数指定と、音声合成が許す尺（56〜61秒）を一致させる。

    もとの指定は「350〜400字」だったが、実測（2026-08-13、青山龍星、
    speedScale=1.0 の6本）では1字あたり約0.171秒で、**350字でも62.25秒**
    あった。つまりどの本数でも必ず範囲外になり、narrate.synthesize() が
    毎回2回目の合成に入っていた。本番尺の合成は1回2分近くかかるので、
    字数指定が外れているだけで実行時間がほぼ倍になる。

    2つの定数が別々に動くと同じズレがまた起きるので、ここで縛る。
    """
    assert (script_writer.NARRATION_MIN_CHARS
            * narrate.SECONDS_PER_CHAR) >= narrate.TARGET_MIN
    assert (script_writer.NARRATION_MAX_CHARS
            * narrate.SECONDS_PER_CHAR) <= narrate.TARGET_MAX


def test_プロンプトとスキーマに同じ字数指定が載る():
    """モデルに渡る2箇所（プロンプトと Field の説明）がズレないこと。"""
    span = f"{script_writer.NARRATION_MIN_CHARS}〜{script_writer.NARRATION_MAX_CHARS}字"
    assert span in build_prompt(RECIPE)
    assert span in Script.model_fields["narration"].description


def test_字幕は40文字以内であることを指示する():
    # ナレーション全文を字幕バンドに流し込むと4行しか描画されず、
    # 毎ビルド切り捨て警告が出る（C2）
    got = build_prompt(RECIPE)
    assert "subtitle" in got
    assert "40文字以内" in got


def test_逐語引用があるとき言い換え禁止の指示が入る():
    # 画面に出るのは quote_excerpt そのもの。言い換えると一次資料の出典
    # キャプションが付いた文字列が一次資料と一致しなくなる（C1）
    got = build_prompt(RECIPE)
    assert "quote_excerpt" in got
    assert "そのまま" in got


def test_figureが空なら数値カードの指示は出さない():
    # 現状の唯一の系統（国会会議録）は figure が常に空。ここで数値を
    # 求めると、モデルが作った値に一次資料の出典が付く原因になる
    assert "figure_value" not in build_prompt(RECIPE)


def test_figureがあるときだけ数値カードの指示が入る():
    recipe = dict(RECIPE, evidence=dict(RECIPE["evidence"], figure="関西空港便が30%減"))
    got = build_prompt(recipe)
    assert "figure_value" in got
    assert "30%減" in got


# --- write() の失敗系。実APIは一切呼ばず、Anthropic クライアントを差し替えて検証する ---
# write() は毎朝の無人実行から呼ばれる。失敗したときログから原因が読み取れないと、
# 投稿が止まっていることに何日も気づけない。ここでは実際にAPIを叩かずに、
# 「認証情報が解決できない」「refusal」「parsed_output が None」の3系統と、
# 正常系の計4パターンを固定する。
#
# 前者2つ（refusal / parsed_output が None）は特定の題材の内容に起因する
# 失敗（ScriptGenerationRejected）、認証エラーはどの題材でも同じ理由で
# 起こる環境不備（ScriptWriterUnavailable）として区別される。呼び出し側
# （run_daily.py）はこの2つを別々に扱う（前者はその題材だけ飛ばし、
# 後者は日次実行全体を中止する）ため、型そのものをここで固定する。


def test_import時点ではanthropicを読み込まない():
    """`import scripts.script_writer` の時点で SDK を読み込まない。

    `anthropic` の import は実測20.3秒かかる（`python -X importtime`）。
    run_daily.py はモジュール先頭で script_writer を import するので、
    **台本生成に到達しない日でもこの20秒を払っていた**。枠が全部埋まって
    いる日は何もせず終わるのに、その前に20秒待つことになる。

    サブプロセスで確かめる。同じプロセス内では他のテストが先に
    anthropic を読み込んでいる可能性があり、判定にならない。
    """
    code = ("import sys; import scripts.script_writer; "
            "sys.exit(1 if 'anthropic' in sys.modules else 0)")
    proc = subprocess.run([sys.executable, "-c", code],
                          cwd=Path(__file__).resolve().parents[1],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, (
        "script_writer を import しただけで anthropic まで読み込んでいる。"
        f"stderr:\n{proc.stderr}")


def test_SDKが無いときは環境不備の例外にする(monkeypatch):
    """遅延 import にしても、失敗の型は変えない。

    素の ImportError のまま出すと、run_daily.py の
    「ScriptWriterUnavailable なら日次実行を即座に中止」の分岐に乗らず、
    スタックトレースだけが出て原因が読み取りにくくなる。
    """
    monkeypatch.setattr(script_writer, "Anthropic", None)
    monkeypatch.setattr(script_writer, "_IMPORT_SDK",
                        lambda: (_ for _ in ()).throw(ImportError("no module")))

    with pytest.raises(ScriptWriterUnavailable, match="anthropic"):
        write(RECIPE)


class _FakeMessages:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def parse(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = _FakeMessages(response=response, error=error)


class _FakeResponse:
    def __init__(self, stop_reason, parsed_output=None, stop_details=None, usage=None):
        self.stop_reason = stop_reason
        self.parsed_output = parsed_output
        self.stop_details = stop_details
        self.usage = usage


def test_認証が解決できないとき原因が分かるメッセージの例外になる(monkeypatch):
    # ANTHROPIC_API_KEY も ANTHROPIC_AUTH_TOKEN も ant auth login のプロファイルも
    # 無いとき、実際の Anthropic SDK は messages.parse() 実行時にこの文言の
    # TypeError を出す（"authentication" を含む）。
    auth_error = TypeError(
        '"Could not resolve authentication method. Expected one of api_key, '
        "auth_token, or credentials to be set. Or for one of the `X-Api-Key` "
        'or `Authorization` headers to be explicitly omitted"'
    )
    monkeypatch.setattr(
        script_writer, "Anthropic", lambda: _FakeClient(error=auth_error))

    with pytest.raises(ScriptWriterUnavailable) as exc_info:
        write(RECIPE)

    msg = str(exc_info.value)
    assert "ANTHROPIC_API_KEY" in msg
    assert "ant auth login" in msg


def test_refusalのとき題材固有の例外になりstop_detailsが含まれる(monkeypatch):
    response = _FakeResponse(
        stop_reason="refusal", stop_details="不適切な内容のため生成を拒否しました")
    monkeypatch.setattr(
        script_writer, "Anthropic", lambda: _FakeClient(response=response))

    with pytest.raises(ScriptGenerationRejected) as exc_info:
        write(RECIPE)

    assert "不適切な内容のため生成を拒否しました" in str(exc_info.value)


def test_parsed_outputがNoneのとき題材固有の例外になりstop_reasonが含まれる(monkeypatch):
    response = _FakeResponse(
        stop_reason="max_tokens", parsed_output=None,
        usage={"output_tokens": 16000})
    monkeypatch.setattr(
        script_writer, "Anthropic", lambda: _FakeClient(response=response))

    with pytest.raises(ScriptGenerationRejected) as exc_info:
        write(RECIPE)

    assert "max_tokens" in str(exc_info.value)


def test_正常時はScriptインスタンスが返る(monkeypatch):
    parsed = Script(
        title="議員定数45削減、その中身は",
        headline="議員定数45削減の中身",
        narration="ナレーション本文。" * 20,
        subtitle="議員定数45削減の中身を読む",
        quote_excerpt="議員定数を四十五削減する",
        figure_label="削減議席数",
        figure_value="45議席",
        tags=["政治", "国会", "議員定数"],
    )
    response = _FakeResponse(stop_reason="end_turn", parsed_output=parsed)
    monkeypatch.setattr(
        script_writer, "Anthropic", lambda: _FakeClient(response=response))

    got = write(RECIPE)

    assert isinstance(got, Script)
    assert got.title == parsed.title


# ── 長尺のパート ─────────────────────────────────────────────

def test_パートの字数指定は長尺の尺の窓に収まる():
    """ショートと同じ理由（test_字数指定は尺の許容範囲に収まる）で縛る。

    パートの字数指定と、build_long が narrate に渡す窓が別々に動くと、
    毎パート再合成に入って実行時間が倍になる。
    """
    from scripts.build_long import SEGMENT_TARGET_MAX, SEGMENT_TARGET_MIN

    assert (script_writer.SEGMENT_MIN_CHARS
            * narrate.SECONDS_PER_CHAR) >= SEGMENT_TARGET_MIN
    assert (script_writer.SEGMENT_MAX_CHARS
            * narrate.SECONDS_PER_CHAR) <= SEGMENT_TARGET_MAX


def test_パートのプロンプトとスキーマに同じ字数指定が載る():
    from scripts.script_writer import SegmentScript, build_segment_prompt
    span = f"{script_writer.SEGMENT_MIN_CHARS}〜{script_writer.SEGMENT_MAX_CHARS}字"

    assert span in build_segment_prompt(RECIPE)
    assert span in SegmentScript.model_fields["narration"].description


def test_パートのプロンプトは逐語での抜き出しを求める():
    # 引用カードに出るのはこの一節そのもの。言い換えられると、一次資料の
    # 出典キャプションが付いた文字列が一次資料と一致しなくなる。
    from scripts.script_writer import build_segment_prompt
    prompt = build_segment_prompt(RECIPE)

    assert "そのまま" in prompt
    assert RECIPE["evidence"]["quote"] in prompt


# ── 導入と結び（モデルを使わない）─────────────────────────────

def test_導入は各題材の見出しだけを読み上げる():
    """導入・結びは一次資料に紐づかないので、**モデルに書かせない。**

    プロンプトで「事実を書くな」と頼む形にすると、守られたかどうかを
    確かめる手段が無い（ナレーションは検証されない）。見出しを差し込む
    定型文にすれば、そもそも新しい事実が入る余地が構造的に無い。
    """
    from scripts.script_writer import intro_narration
    text = intro_narration(["アイウ", "エオカ", "キクケ"])

    assert "アイウ" in text and "エオカ" in text and "キクケ" in text


def test_導入と結びの字数は窓に収まる():
    from scripts.build_long import (INTRO_TARGET_MAX, INTRO_TARGET_MIN,
                                    OUTRO_TARGET_MAX, OUTRO_TARGET_MIN)
    from scripts.script_writer import intro_narration, outro_narration

    intro = len(intro_narration(["あ" * 20] * 3)) * narrate.SECONDS_PER_CHAR
    outro = len(outro_narration()) * narrate.SECONDS_PER_CHAR

    assert INTRO_TARGET_MIN <= intro <= INTRO_TARGET_MAX
    assert OUTRO_TARGET_MIN <= outro <= OUTRO_TARGET_MAX


def test_短い見出しでも導入は窓に収まる():
    from scripts.build_long import INTRO_TARGET_MAX, INTRO_TARGET_MIN
    from scripts.script_writer import intro_narration

    intro = len(intro_narration(["アイ", "ウエ", "オカ"])) * narrate.SECONDS_PER_CHAR

    assert INTRO_TARGET_MIN <= intro <= INTRO_TARGET_MAX
