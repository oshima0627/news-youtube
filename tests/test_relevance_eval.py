import json

import pytest

from scripts import relevance_eval
from scripts.relevance_eval import (
    RelevanceEvalUnavailable,
    Verdict,
    build_prompt,
    judge,
    summarize,
)

RECIPE = {
    "id": "abc123",
    "headline": "公的年金積立金 過去最高302兆円余 令和7年度決算",
    "keyword": "年金 積立 最高",
    "category": "政治",
    "evidence": {
        "kind": "speech",
        "source_url": "https://kokkai.ndl.go.jp/txt/121314370X01320240514/78",
        "figure": "",
        "quote": "ＧＰＩＦは、平均すると四％ほどの利回りで資金を運用しています。",
        "context": "第213回国会 参議院財政金融委員会 2024-05-14 神谷宗幣",
    },
}

RUBRIC = "# 採点基準\n5点は出来事を直接扱っているもの。1点は出来事が存在しないもの。"


class _FakeMessages:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = _FakeMessages(response=response, error=error)


class _FakeResponse:
    def __init__(self, stop_reason="end_turn", parsed_output=None):
        self.stop_reason = stop_reason
        self.parsed_output = parsed_output


def _verdict(score=3):
    return Verdict(event="政府が年金積立金の決算を公表した", score=score,
                   reason="時点が2年ずれている", timing_ok=False, lead_ok=True)


# --- プロンプトに何を渡すか ---------------------------------------------

def test_見出しと逐語引用がプロンプトに入る():
    got = build_prompt(RECIPE, RUBRIC)
    assert "公的年金積立金" in got
    assert "四％ほどの利回り" in got


def test_採点基準がプロンプトに入る():
    # 基準はファイルが持つ。スクリプトに埋め込むと二重管理になる
    assert RUBRIC in build_prompt(RECIPE, RUBRIC)


def test_公開タイトルと台本は評価者に渡さない():
    """引用に寄せて作られた成果物を見せると、採点が別の判定にすり替わる。"""
    recipe = dict(RECIPE, script={"title": "GPIF「平均4%の利回り」国会で語られた年金運用の実像"},
                  youtube_title="GPIF「平均4%の利回り」国会で語られた年金運用の実像")
    got = build_prompt(recipe, RUBRIC)
    assert "実像" not in got


def test_採点は生成側と別のモデルを使う():
    # 同じモデルに書かせて同じモデルに採点させると自己評価バイアスが乗る
    from scripts import script_writer
    assert relevance_eval.MODEL != script_writer.MODEL


# --- 環境不備の扱い -----------------------------------------------------

def test_SDKが無いときは理由の分かる例外になる(monkeypatch):
    monkeypatch.setattr(relevance_eval, "Anthropic", None)
    monkeypatch.setattr(relevance_eval, "_IMPORT_SDK",
                        lambda: (_ for _ in ()).throw(ImportError("no module")))
    with pytest.raises(RelevanceEvalUnavailable, match="anthropic"):
        judge(RECIPE, RUBRIC)


def test_認証が解決できないとき原因が分かるメッセージの例外になる(monkeypatch):
    monkeypatch.setattr(
        relevance_eval, "Anthropic",
        lambda: _FakeClient(error=TypeError("missing authentication")))
    with pytest.raises(RelevanceEvalUnavailable, match="認証情報"):
        judge(RECIPE, RUBRIC)


def test_認証以外のTypeErrorは握りつぶさない(monkeypatch):
    monkeypatch.setattr(
        relevance_eval, "Anthropic",
        lambda: _FakeClient(error=TypeError("unexpected keyword argument")))
    with pytest.raises(TypeError):
        judge(RECIPE, RUBRIC)


def test_ルーブリックが無いときは例外にする(monkeypatch, tmp_path):
    """基準なしで採点を続けると、高い点が返って「合格した」ように見える。"""
    monkeypatch.setattr(relevance_eval, "RUBRIC", tmp_path / "nope.md")
    with pytest.raises(RelevanceEvalUnavailable, match="採点基準"):
        relevance_eval.load_rubric()


def test_構造化出力を受け取れないときは例外にする(monkeypatch):
    monkeypatch.setattr(
        relevance_eval, "Anthropic",
        lambda: _FakeClient(response=_FakeResponse(stop_reason="max_tokens")))
    with pytest.raises(RelevanceEvalUnavailable, match="max_tokens"):
        judge(RECIPE, RUBRIC)


def test_正常時はVerdictが返る(monkeypatch):
    monkeypatch.setattr(
        relevance_eval, "Anthropic",
        lambda: _FakeClient(response=_FakeResponse(parsed_output=_verdict(5))))
    got = judge(RECIPE, RUBRIC)
    assert got.score == 5


# --- 合否の判定 ---------------------------------------------------------

def test_1点が1件でもあれば不合格():
    """クリティカル項目。他が満点でもスコアの高さで買い戻せない。"""
    results = [(RECIPE, _verdict(5)) for _ in range(9)]
    results.append(({"id": "bad"}, _verdict(1)))
    s = summarize(results)
    assert s["passed"] is False
    assert s["critical_ids"] == ["bad"]


def test_3点以下が3分の1を超えたら不合格():
    results = [(RECIPE, _verdict(5)) for _ in range(6)]
    results += [(RECIPE, _verdict(3)) for _ in range(4)]
    assert summarize(results)["passed"] is False


def test_3点以下が3分の1ちょうどなら合格():
    results = [(RECIPE, _verdict(5)) for _ in range(6)]
    results += [(RECIPE, _verdict(3)) for _ in range(3)]
    s = summarize(results)
    assert s["passed"] is True
    assert s["score5"] == 6


def test_ベースラインと同じ配分では不合格になる():
    """evals/relevance-baseline-2026-08-13.md の実測（5点4件/3点6件/1点1件）。

    この配分で合格が出るなら合格ラインが緩すぎる。
    """
    results = [(dict(RECIPE, id=f"g{i}"), _verdict(5)) for i in range(4)]
    results += [(dict(RECIPE, id=f"m{i}"), _verdict(3)) for i in range(6)]
    results += [({"id": "8b000ae446da"}, _verdict(1))]
    s = summarize(results)
    assert s["total"] == 11
    assert s["score5"] == 4
    assert s["passed"] is False


# --- CLI ---------------------------------------------------------------

def test_合格ラインを外したら終了コードが非ゼロ(monkeypatch, tmp_path, capsys):
    (tmp_path / "abc123.json").write_text(
        json.dumps(RECIPE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(relevance_eval, "RECIPES", tmp_path)
    monkeypatch.setattr(relevance_eval, "load_rubric", lambda: RUBRIC)
    monkeypatch.setattr(relevance_eval, "judge", lambda r, rb: _verdict(1))
    assert relevance_eval.main([]) == 1
    assert "1点" in capsys.readouterr().out


def test_採点対象が無いときは非ゼロで止まる(monkeypatch, tmp_path):
    monkeypatch.setattr(relevance_eval, "RECIPES", tmp_path)
    assert relevance_eval.main([]) == 1
