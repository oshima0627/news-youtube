"""視聴維持率と流入元を測る診断CLIのテスト。

2026-08-27 の実測で、**チャンネルの再生の96%がショートのフィードから来ていて、
長尺は同じ期間で0再生**だった。長尺の不振を「題材かサムネイルか」で考えていたが、
そもそも長尺が乗る面が無い、という別の事実が出た。同じことを毎回手で調べ直さずに
済むよう、判定をここに固定する。

外部（YouTube Analytics API）は呼ばない。返ってきた行の並べ替え・絞り込み・
割合の計算だけを検証する。
"""

from __future__ import annotations

from scripts.retention_report import Video, rank, render, traffic_share

# Analytics API が返す行の形。dimensions=video, metrics=views,averageViewPercentage,likes
ROWS = [
    ["short_a", 14312, 152.8, 151],
    ["short_b", 1108, 57.5, 13],
    ["short_c", 25, 32.8, 0],
    ["old_one", 9999, 80.0, 5],      # パイプライン産ではない古い動画
]

MINE = {"short_a", "short_b", "short_c"}

TITLES = {
    "short_a": "食料品の消費税1%で減収4.3兆円",
    "short_b": "七戸に一戸が空き家",
    "short_c": "避難所に暑さの基準がない",
}


def test_パイプライン産の動画だけを対象にする():
    """チャンネルには手作りの古い動画が150本以上ある。混ぜると、
    パイプラインの良し悪しを見ているつもりで別のものを見ることになる。
    """
    got = rank(ROWS, MINE)
    assert [v.video_id for v in got] == ["short_a", "short_b", "short_c"]


def test_再生数の多い順に並べる():
    got = rank(ROWS, MINE)
    assert [v.views for v in got] == [14312, 1108, 25]


def test_対象が1本も無ければ空で返す():
    assert rank(ROWS, set()) == []


def test_流入元の割合を出す():
    rows = [["SHORTS", 14953], ["YT_SEARCH", 488], ["YT_CHANNEL", 23]]
    got = traffic_share(rows)
    assert [s for s, _, _ in got] == ["SHORTS", "YT_SEARCH", "YT_CHANNEL"]
    assert got[0][1] == 14953
    assert round(got[0][2], 1) == 96.7


def test_流入元が0件でも壊れない():
    """公開直後や、再生が1件も無い期間を指定したときに通る道。
    ここで ZeroDivisionError を出すと、原因が分からないまま診断が止まる。
    """
    assert traffic_share([]) == []
    assert traffic_share([["SHORTS", 0]]) == [("SHORTS", 0, 0.0)]


def test_表示にはタイトルと数字が両方出る():
    lines = render(rank(ROWS, MINE), TITLES)
    joined = "\n".join(lines)
    assert "14312" in joined
    assert "食料品の消費税1%で減収4.3兆円" in joined
    assert "152.8" in joined


def test_タイトルが引けない動画はIDで出す():
    """videos.list が返さない（削除済み等）場合に、行ごと消さない。
    消すと『測った本数』が黙って減る。
    """
    lines = render([Video("unknown", 10, 50.0, 0)], {})
    assert "unknown" in "\n".join(lines)
