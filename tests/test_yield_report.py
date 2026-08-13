"""採用ゲートの歩留まりを測る診断CLIのテスト。

`state/empty_streak.json` の警告は0本が3日続いてから出る。収益化要件
（90日で3本以上）に対しては遅いので、「今日どれくらい余裕があったか」を
その日のうちに見られるようにしてある。ここでは判定そのものを固定する。
"""

from __future__ import annotations

from scripts.evidence import Evidence
from scripts.yield_report import (
    NO_EVIDENCE,
    SAME_SPEECH,
    SAME_TOPIC,
    USABLE,
    classify,
    summarize,
)


def _cand(cid: str, keyword: str, title: str = "見出し") -> dict:
    return {"id": cid, "title": title, "keyword": keyword}


def _ev(url: str) -> Evidence:
    return Evidence(kind="speech", source_url=url, figure="",
                    quote="十二文字以上ある逐語引用です", context="文脈")


def test_検索語が2語重なる候補は同じ出来事として落ちる():
    rows = classify([_cand("a", "消費 減税 食料品")],
                    used_urls=set(), used_words=[{"消費", "減税", "基本"}],
                    collect_fn=lambda kw: [_ev("https://example.com/1")])
    assert rows[0].status == SAME_TOPIC
    # 一次資料に当てに行かない（無駄な照会をしない）
    assert rows[0].found == 0


def test_1語しか重ならなければ別の出来事として扱う():
    rows = classify([_cand("a", "年金 積立 運用")],
                    used_urls=set(), used_words=[{"年金", "医療", "介護"}],
                    collect_fn=lambda kw: [_ev("https://example.com/1")])
    assert rows[0].status == USABLE


def test_根拠が取れない候補は根拠なしになる():
    rows = classify([_cand("a", "外国 共生 社会")],
                    used_urls=set(), used_words=[],
                    collect_fn=lambda kw: [])
    assert rows[0].status == NO_EVIDENCE


def test_取れた根拠が全部既出なら同じ発言として落ちる():
    url = "https://kokkai.ndl.go.jp/txt/1/2"
    rows = classify([_cand("a", "外国 共生 社会")],
                    used_urls={url}, used_words=[],
                    collect_fn=lambda kw: [_ev(url)])
    assert rows[0].status == SAME_SPEECH
    assert rows[0].found == 1
    assert rows[0].fresh == 0


def test_一部でも新しい発言が残れば採用可():
    used = "https://kokkai.ndl.go.jp/txt/1/2"
    rows = classify([_cand("a", "外国 共生 社会")],
                    used_urls={used}, used_words=[],
                    collect_fn=lambda kw: [_ev(used),
                                           _ev("https://kokkai.ndl.go.jp/txt/3/4")])
    assert rows[0].status == USABLE
    assert rows[0].fresh == 1


def test_一次資料の取得元が落ちていても止めずに記録する():
    """診断が例外で止まると「測れなかった」ことすら分からない。"""
    def _boom(keyword):
        raise RuntimeError("接続できません")

    rows = classify([_cand("a", "外国 共生 社会")],
                    used_urls=set(), used_words=[], collect_fn=_boom)
    assert "接続できません" in rows[0].status


def test_要約は採用可の件数と最上位の順位を返す():
    rows = classify(
        [_cand("a", "天気 予報 明日"), _cand("b", "外国 共生 社会")],
        used_urls=set(), used_words=[],
        collect_fn=lambda kw: [] if kw.startswith("天気") else [_ev("u")])

    got = summarize(rows, slots=2)

    assert got["usable"] == 1
    assert got["first_usable_rank"] == 2      # 1件目は根拠なしなので2番目
    assert got["counts"][NO_EVIDENCE] == 1
    assert got["short_of_slots"] is True      # 2枠に対して1件しか無い


def test_採用可が0件なら最上位の順位は無い():
    rows = classify([_cand("a", "天気 予報 明日")],
                    used_urls=set(), used_words=[], collect_fn=lambda kw: [])
    got = summarize(rows, slots=2)
    assert got["usable"] == 0
    assert got["first_usable_rank"] is None
    assert got["short_of_slots"] is True
