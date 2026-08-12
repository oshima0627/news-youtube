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


def _segments(*pairs: tuple[str, int]) -> list[dict]:
    return [{"text": t, "moras": n} for t, n in pairs]


# --- 本文の切り分け ---------------------------------------------------------

def test_句読点の直後で切る():
    got = telop.split_segments("消費税の減税が決まった。野党は反発している、と報じられた。")

    assert got == ["消費税の減税が決まった。", "野党は反発している、", "と報じられた。"]


# --- 音声側の区切り ---------------------------------------------------------

def test_子音の長さもモーラの長さに含める():
    # 「カ」のようなモーラは子音＋母音で1拍。母音だけ足すと全体が短く出て、
    # テロップが音より先に進む。
    q = _query([{"moras": [{"text": "カ", "consonant_length": 0.06,
                            "vowel_length": 0.1}]}])

    assert telop.mora_timeline(q) == pytest.approx([0.16])


def test_モーラを1つずつ並べる():
    q = _query([_phrase(1.0), _phrase(0.5, pause=0.2), _phrase(2.0)])

    # 間（pause_mora）は直前のモーラに足し込む。本文の文字に対応しないので
    # 独立した要素にするとモーラ数の突き合わせが合わなくなる。
    assert telop.mora_timeline(q) == pytest.approx([1.0, 0.7, 2.0])


def test_speedScaleで割って実時間にする():
    # 尺補正で speedScale が 1.0 でない状態が普通。割らないと全部ずれる。
    slow = telop.mora_timeline(_query([_phrase(2.0)], speed=1.0))
    fast = telop.mora_timeline(_query([_phrase(2.0)], speed=2.0))

    assert slow == pytest.approx([2.0])
    assert fast == pytest.approx([1.0])


def test_前後の無音を端のモーラに含める():
    q = _query([_phrase(1.0), _phrase(1.0)], pre=0.1, post=0.2)

    assert telop.mora_timeline(q) == pytest.approx([1.1, 1.2])


# --- 割り付け ---------------------------------------------------------------

def test_本文と音声をモーラ数で対応づける():
    # MERGE_UNDER 以上の長さにしておく（短い区切りは次とつながるため）
    segs = _segments(("これは最初の一文になります。", 1), ("これは次の一文になります。", 1))
    q = _query([_phrase(2.0, pause=0.0), _phrase(3.0)])

    got = telop.spans(segs, q)

    assert [t for t, _, _ in got] == ["これは最初の一文になります。", "これは次の一文になります。"]
    assert [(round(s, 3), round(e, 3)) for _, s, e in got] == [(0.0, 2.0), (2.0, 5.0)]


def test_モーラ数が合わなければ割り付けない():
    # 無理に割り当てると音とずれたテロップが出続ける。呼び出し側が
    # 静止字幕に戻せるよう None を返す。
    segs = _segments(("一文目。", 3), ("二文目。", 3))
    q = _query([_phrase(1.0), _phrase(1.0)])      # モーラは2個しかない

    assert telop.spans(segs, q) is None


def test_区切りの数が音声とずれていても割り付けられる():
    # VOICEVOX は句読点以外にも間を入れるので、区切りの数は一致しない。
    # 実測3本中2本がこれで落ちてテロップがまったく付かなかった。
    segs = _segments(("これは最初の一文になります。", 2), ("これは次の一文になります。", 2))
    q = _query([_phrase(1.0, pause=0.5), _phrase(1.0, pause=0.5),
                _phrase(2.0), _phrase(2.0)])      # 区切りは4個、本文は2個

    got = telop.spans(segs, q)

    assert got is not None
    assert [t for t, _, _ in got] == ["これは最初の一文になります。", "これは次の一文になります。"]
    assert got[0][2] == pytest.approx(3.0)


def test_短い区切りは次とつなげる():
    # 「ポイントは、」だけが0.6秒出て消えるのは読めない。
    segs = _segments(("ポイントは、", 1), ("この制度がいつから始まるのかという点にあります。", 1))
    q = _query([_phrase(0.6), _phrase(4.0)])

    got = telop.spans(segs, q)

    assert got[0][0].startswith("ポイントは、この制度")
    assert got[0][1] == 0.0


def test_長い区切りは分割して全部の文字を残す():
    a, b = "これは非常に長い一文であり、", "同じ内容が続きます。"
    segs = _segments((a, 1), (b, 1))
    q = _query([_phrase(2.0), _phrase(3.0)])

    got = telop.spans(segs, q)

    assert "".join(t for t, _, _ in got) == a + b
    assert all(len(t) <= telop.MAX_CHARS + 2 for t, _, _ in got)


def test_分割は語の途中で切らない():
    # 文字数だけで割ると「食料品にかか／る付加価値税」になる。
    text = "片山さつき大臣がG7各国の食料品にかかる付加価値税について答弁しています。"
    q = _query([_phrase(5.0)])

    got = telop.spans(_segments((text, 1)), q)

    assert len(got) == 2
    assert not got[1][0].startswith("る")
    assert "".join(t for t, _, _ in got) == text


def test_テロップの漢数字も算用数字にする():
    q = _query([_phrase(2.0)])

    got = telop.spans(_segments(("税率は一〇パーセントです。", 1)), q)

    assert got[0][0] == "税率は10パーセントです。"


def test_時刻は途切れずつながる():
    segs = _segments(("これは最初の一文です。", 1), ("これは二番目の一文です。", 1),
                     ("これは三番目の一文です。", 1))
    q = _query([_phrase(1.0), _phrase(2.0), _phrase(3.0)])

    got = telop.spans(segs, q)

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
    assert telop.spans([], _query([])) is None
