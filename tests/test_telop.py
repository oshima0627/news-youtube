"""ナレーションに同期したテロップの割り付けのテスト。

VOICEVOX は叩かない。`/audio_query` が返す形の辞書を組み立てて、
そこから計算した時刻と本文の対応だけを確かめる。
"""

import pytest

from scripts import telop


def _mora(length: float) -> dict:
    return {"text": "ア", "consonant_length": 0.0, "vowel_length": length}


def _phrase(seconds: float, pause: float | None = None) -> dict:
    p = {"moras": [_mora(seconds)]}
    if pause is not None:
        p["pause_mora"] = {"text": "、", "vowel_length": pause}
    return p


def _query(phrases: list[dict], speed: float = 1.0,
           pre: float = 0.0, post: float = 0.0) -> dict:
    return {"accent_phrases": phrases, "speedScale": speed,
            "prePhonemeLength": pre, "postPhonemeLength": post}


# --- 本文の切り分け ---------------------------------------------------------

def test_句読点の直後で切る():
    got = telop.split_segments("消費税の減税が決まった。野党は反発している、と報じられた。")

    assert got == ["消費税の減税が決まった。", "野党は反発している、", "と報じられた。"]


# --- 音声側の区切り ---------------------------------------------------------

def test_pause_moraごとに区切って実時間にする():
    q = _query([_phrase(1.0), _phrase(0.5, pause=0.2), _phrase(2.0)])

    assert telop.group_durations(q) == pytest.approx([1.7, 2.0])


def test_speedScaleで割って実時間にする():
    # 尺補正で speedScale が 1.0 でない状態が普通。割らないと全部ずれる。
    slow = telop.group_durations(_query([_phrase(2.0, pause=0.0)], speed=1.0))
    fast = telop.group_durations(_query([_phrase(2.0, pause=0.0)], speed=2.0))

    assert slow == pytest.approx([2.0])
    assert fast == pytest.approx([1.0])


def test_前後の無音を端のかたまりに含める():
    q = _query([_phrase(1.0, pause=0.0), _phrase(1.0)], pre=0.1, post=0.2)

    assert telop.group_durations(q) == pytest.approx([1.1, 1.2])


# --- 割り付け ---------------------------------------------------------------

def test_本文と音声を順に対応づける():
    # MERGE_UNDER 以上の長さにしておく（短い区切りは次とつながるため）
    text = "これは最初の一文になります。これは次の一文になります。"
    q = _query([_phrase(2.0, pause=0.0), _phrase(3.0)])

    got = telop.spans(text, q)

    assert [t for t, _, _ in got] == ["これは最初の一文になります。", "これは次の一文になります。"]
    assert [(round(s, 3), round(e, 3)) for _, s, e in got] == [(0.0, 2.0), (2.0, 5.0)]


def test_区切りの数が合わなければ割り付けない():
    # 無理に割り当てると音とずれたテロップが出続ける。呼び出し側が
    # 静止字幕に戻せるよう None を返す。
    text = "一文目。二文目。三文目。"
    q = _query([_phrase(1.0, pause=0.0), _phrase(1.0)])

    assert telop.spans(text, q) is None


def test_短い区切りは次とつなげる():
    # 「ポイントは、」だけが0.6秒出て消えるのは読めない。
    text = "ポイントは、この制度がいつから始まるのかという点にあります。"
    q = _query([_phrase(0.6, pause=0.0), _phrase(4.0)])

    got = telop.spans(text, q)

    assert got[0][0].startswith("ポイントは、この制度")
    assert got[0][1] == 0.0


def test_長い区切りは分割して全部の文字を残す():
    long_text = "これは非常に長い一文であり、" + "同じ内容が続きます。"
    text = long_text
    q = _query([_phrase(2.0, pause=0.0), _phrase(3.0)])

    got = telop.spans(text, q)

    assert "".join(t for t, _, _ in got) == text.replace("、", "、")
    assert all(len(t) <= telop.MAX_CHARS + 2 for t, _, _ in got)


def test_分割は語の途中で切らない():
    # 文字数だけで割ると「食料品にかか／る付加価値税」になる。
    text = "片山さつき大臣がG7各国の食料品にかかる付加価値税について答弁しています。"
    q = _query([_phrase(5.0)])

    got = telop.spans(text, q)

    assert len(got) == 2
    assert not got[1][0].startswith("る")
    assert "".join(t for t, _, _ in got) == text


def test_テロップの漢数字も算用数字にする():
    text = "税率は一〇パーセントです。"
    q = _query([_phrase(2.0)])

    got = telop.spans(text, q)

    assert got[0][0] == "税率は10パーセントです。"


def test_時刻は途切れずつながる():
    text = "これは最初の一文です。これは二番目の一文です。これは三番目の一文です。"
    q = _query([_phrase(1.0, pause=0.0), _phrase(2.0, pause=0.0), _phrase(3.0)])

    got = telop.spans(text, q)

    for previous, following in zip(got, got[1:]):
        assert previous[2] == pytest.approx(following[1])


# --- 実尺への合わせ込み -----------------------------------------------------

def test_合計をwavの実尺にそろえる():
    # 計算値と wav は数十ミリ秒ずれる。そのままだと映像が音より長くなる。
    items = [("あ", 0.0, 1.0), ("い", 1.0, 3.0)]

    got = telop.stretch(items, 6.0)

    assert got[-1][2] == pytest.approx(6.0)
    assert got[0][2] == pytest.approx(2.0)


def test_空でも壊れない():
    assert telop.stretch([], 5.0) == []
    assert telop.spans("", _query([])) is None
