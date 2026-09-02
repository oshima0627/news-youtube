"""選挙用の一次資料ゲート（候補者の公約ページ）のテスト。

ここで縛りたいのは1点に尽きる: **run_daily.py の関門を迂回する穴にしない**こと。
この経路は evidence.collect() を通らないので、検証をここに置き切らないと
「一次資料付きに見えるが誰も中身を確かめていない動画」ができる。
"""
import pytest

from scripts import election


KOJA = "koja"
TAMAKI = "tamaki"

# 公約ページの中身を模したもの。実際の取得は _fetch を差し替えて止める。
PAGE = (
    "古謝げんたの政策　ひとりあたり県民所得231.5万円を500万円にふやす。"
    "沖縄県こども未来部の予算552億円を1000億円にふやす。"
    "観光収入1兆747億円を2兆円にふやす。"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(election, "_fetch", lambda url: PAGE)


def test_許可リストは両候補の公約ページを持つ():
    # 片方だけになっていたら、この経路は一方の候補の宣伝装置になる。
    assert set(election.MANIFESTO_SOURCES) == {KOJA, TAMAKI}


def test_許可リストに無い候補は通さない():
    with pytest.raises(election.UnknownCandidate):
        election.collect("someone", "ひとりあたり県民所得231.5万円")


def test_引用がページに逐語で無ければ通さない():
    # 一次資料に書かれていない文章に出典キャプションが付くのを防ぐ関門。
    with pytest.raises(election.QuoteNotFound):
        election.collect(KOJA, "県民所得を1000万円にふやす")


def test_引用がページにあれば採用する():
    ev = election.collect(KOJA, "ひとりあたり県民所得231.5万円を500万円にふやす")
    assert ev.kind == "manifesto"
    assert ev.source_url == election.MANIFESTO_SOURCES[KOJA].url
    assert "231.5万円" in ev.quote


def test_短すぎる引用は通さない():
    # 「500万円」だけを引用にすると、文脈が消えて何の数字か分からなくなる。
    with pytest.raises(election.QuoteNotFound):
        election.collect(KOJA, "500万円")


def test_source_url_は許可リストの値と完全一致する():
    # ページ内の別URLや短縮URLに差し替わっていないこと。
    for key, src in election.MANIFESTO_SOURCES.items():
        assert src.url.startswith("https://")
        ev = election.collect(key, "ひとりあたり県民所得231.5万円を500万円にふやす")
        assert ev.source_url == src.url


def test_発言者は候補者本人の名前になる():
    # commons.resolve がこの名前で ja.wikipedia の記事画像を引く。
    ev = election.collect(KOJA, "ひとりあたり県民所得231.5万円を500万円にふやす")
    assert ev.speaker == election.MANIFESTO_SOURCES[KOJA].person


def test_数値カードに出せるのは実際の数量だけ():
    from scripts.evidence import has_figure
    ev = election.collect(KOJA, "ひとりあたり県民所得231.5万円を500万円にふやす",
                          figure="500万円")
    assert has_figure(ev.figure)


def test_数量でない_figure_は拒否する():
    with pytest.raises(ValueError):
        election.collect(KOJA, "ひとりあたり県民所得231.5万円を500万円にふやす",
                         figure="2026年度")


def test_空白のゆれは吸収するが文字は落とさない():
    # ページ側の改行・全角空白でだけ落ちるのは関門として無意味。
    # ただし文字そのものが違うものは通さない（上の QuoteNotFound で担保）。
    ev = election.collect(KOJA, "県民所得231.5万円 を 500万円にふやす")
    assert ev.quote  # 空白を詰めれば一致する
