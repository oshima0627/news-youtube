"""長尺の組み立て。

ショート（build_short.py）と分けてある理由は
docs/superpowers/specs/2026-08-20-long-form-design.md を参照。
"""

import json

import pytest

from scripts import build_long
from scripts.cards_wide import WIDE_SIZE

SOURCE = "参議院予算委員会 2026年6月16日 片山さつき"
QUOTE = "イタリアは基本的な食料品は四％でありますが、肉や魚は一〇％となっております"


# --- 引用カードの関門（ショートと同じものを通す）-----------------------------

def test_モデルが捏造した一節は逐語引用から機械抽出した文字列に差し替わる(tmp_path):
    """引用カードには一次資料の出典キャプションが必ず付く。したがって
    カードに出る文字列は一次資料に由来していなければならない。

    ショートでは build_short.compose_base がこの関門を通している。
    長尺で通さないと、同じ画面に緩い基準で作った文字列が乗る。
    """
    photo = _photo(tmp_path)
    invented = {"headline": "見出し", "subtitle": "字幕",
                "quote_excerpt": "一次資料に無い言い回し"}

    img = build_long.compose_segment(photo, invented, SOURCE, 1, quote=QUOTE)
    grounded = build_long.compose_segment(
        photo, {**invented, "quote_excerpt": QUOTE[:25]}, SOURCE, 1, quote=QUOTE)

    from PIL import ImageChops
    assert ImageChops.difference(img.convert("RGB"),
                                 grounded.convert("RGB")).getbbox() is None


def test_逐語引用を渡さない経路は描画できない(tmp_path):
    # キーワード必須引数にしてあるので、渡し忘れた経路は描けない。
    with pytest.raises(TypeError):
        build_long.compose_segment(_photo(tmp_path), {"headline": "見",
                                                      "subtitle": "字",
                                                      "quote_excerpt": "抜"},
                                   SOURCE, 1)


def test_組んだ画面は1920x1080で返る(tmp_path):
    img = build_long.compose_segment(_photo(tmp_path),
                                     {"headline": "見出し", "subtitle": "字幕",
                                      "quote_excerpt": QUOTE[:20]},
                                     SOURCE, 1, quote=QUOTE)
    assert img.size == WIDE_SIZE


def test_導入と結びの画面には出典キャプションを出さない(tmp_path):
    # この2パートは一次資料に紐づかない。出典の付いた要素を置かない。
    img = build_long.compose_bumper(["ア", "イ", "ウ"], "きょうの3つの論点")
    assert img.size == WIDE_SIZE


# --- パートを跨いだテロップの時刻 --------------------------------------------

def test_テロップの時刻はパートの開始位置ぶんずれる():
    """パートごとに 0 秒から数えた時刻を、通しの時刻に直す。

    ずらし忘れると、2章目以降のテロップが動画の冒頭に重なって出て、
    残りは1枚も出ない。
    """
    parts = [
        [("ア", 0.0, 2.0), ("イ", 2.0, 5.0)],
        [("ウ", 0.0, 3.0)],
    ]
    got = build_long.join_frames(parts, [5.0, 3.0])

    assert got == [("ア", 0.0, 2.0), ("イ", 2.0, 5.0), ("ウ", 5.0, 8.0)]


def test_テロップが作れなかったパートは静止字幕で埋まる():
    # そのパートだけ無音の帯になるのを防ぐ。
    got = build_long.join_frames([None, [("ウ", 0.0, 3.0)]], [4.0, 3.0],
                                 fallbacks=["字幕1", "字幕2"])

    assert got == [("字幕1", 0.0, 4.0), ("ウ", 4.0, 7.0)]


# --- 章（チャプター）---------------------------------------------------------

def test_章の書式はYouTubeの仕様に合わせる():
    got = build_long.chapters(["きょうの論点", "消費税の実態", "在留外国人"],
                              [14.2, 75.4, 80.1])

    assert got == ["00:00 きょうの論点",
                   "00:14 消費税の実態",
                   "01:29 在留外国人"]


def test_章は必ず0秒から始まる():
    # YouTube は最初の章が 00:00 でないと章として認識しない。
    got = build_long.chapters(["導入", "①", "②"], [10.0, 60.0, 60.0])
    assert got[0].startswith("00:00")


def test_10秒未満の章があれば警告する(capsys):
    # YouTube の章は各10秒以上。短い章があると章立てごと無効になる。
    build_long.chapters(["導入", "①", "②"], [4.0, 60.0, 60.0])
    out = capsys.readouterr().out

    assert "10秒" in out


# --- 尺の検証 ---------------------------------------------------------------

def test_音声の合計とmp4の実尺がずれたら警告する(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(build_long, "mp4_duration_seconds", lambda p: 200.0)
    build_long.verify_duration(tmp_path / "video.mp4", 240.0)
    out = capsys.readouterr().out

    assert "警告" in out


def test_ずれが許容内なら警告しない(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(build_long, "mp4_duration_seconds", lambda p: 239.5)
    build_long.verify_duration(tmp_path / "video.mp4", 240.0)

    assert "警告" not in capsys.readouterr().out


# --- 台本の字数と尺の窓 ------------------------------------------------------

def test_パートの窓は合成の可動域に収まる():
    """speedScale の可動域は 0.85〜1.35。窓の幅がこれより広いと、
    窓に入れるための補正が可動域に張り付いて入りきらない。
    """
    from scripts import narrate
    from scripts import script_writer as sw

    natural_min = sw.SEGMENT_MIN_CHARS * narrate.SECONDS_PER_CHAR
    natural_max = sw.SEGMENT_MAX_CHARS * narrate.SECONDS_PER_CHAR
    mid = (build_long.SEGMENT_TARGET_MIN + build_long.SEGMENT_TARGET_MAX) / 2

    assert narrate.SPEED_MIN <= natural_min / mid
    assert natural_max / mid <= narrate.SPEED_MAX


def _photo(tmp_path):
    from PIL import Image
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (600, 900), (90, 90, 90)).save(path)
    return path


def test_どのパートも章の最短時間を下回らない():
    """YouTube の章は各10秒以上。1つでも下回ると**章立てごと無効**になる。

    導入・結びは定型文なので短くなりやすい（実測で結びが7.9秒だった）。
    尺の窓の下限を章の条件に合わせておけば、定型文を書き換えたときに
    テストで気づける。
    """
    for name, low in (("導入", build_long.INTRO_TARGET_MIN),
                      ("結び", build_long.OUTRO_TARGET_MIN),
                      ("題材", build_long.SEGMENT_TARGET_MIN)):
        assert low >= build_long.CHAPTER_MIN_SECONDS, name
