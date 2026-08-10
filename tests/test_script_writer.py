import pytest

from scripts import script_writer
from scripts.script_writer import Script, build_prompt, write

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
    assert "350" in got and "400" in got


# --- write() の失敗系。実APIは一切呼ばず、Anthropic クライアントを差し替えて検証する ---
# write() は毎朝の無人実行から呼ばれる。失敗したときログから原因が読み取れないと、
# 投稿が止まっていることに何日も気づけない。ここでは実際にAPIを叩かずに、
# 「認証情報が解決できない」「refusal」「parsed_output が None」の3系統と、
# 正常系の計4パターンを固定する。


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

    with pytest.raises(RuntimeError) as exc_info:
        write(RECIPE)

    msg = str(exc_info.value)
    assert "ANTHROPIC_API_KEY" in msg
    assert "ant auth login" in msg


def test_refusalのとき例外になりstop_detailsが含まれる(monkeypatch):
    response = _FakeResponse(
        stop_reason="refusal", stop_details="不適切な内容のため生成を拒否しました")
    monkeypatch.setattr(
        script_writer, "Anthropic", lambda: _FakeClient(response=response))

    with pytest.raises(RuntimeError) as exc_info:
        write(RECIPE)

    assert "不適切な内容のため生成を拒否しました" in str(exc_info.value)


def test_parsed_outputがNoneのとき例外になりstop_reasonが含まれる(monkeypatch):
    response = _FakeResponse(
        stop_reason="max_tokens", parsed_output=None,
        usage={"output_tokens": 16000})
    monkeypatch.setattr(
        script_writer, "Anthropic", lambda: _FakeClient(response=response))

    with pytest.raises(RuntimeError) as exc_info:
        write(RECIPE)

    assert "max_tokens" in str(exc_info.value)


def test_正常時はScriptインスタンスが返る(monkeypatch):
    parsed = Script(
        title="議員定数45削減、その中身は",
        headline="議員定数45削減の中身",
        narration="ナレーション本文。" * 20,
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
