import json
import subprocess
import wave
from datetime import date
from pathlib import Path

import pytest

from scripts.build_live_loop import (WINDOW_HIGH, WINDOW_LOW,
                                     ExcludeCategoryNotFound, narration_text,
                                     render_frame, select_recipes,
                                     shuffle_for_date, speech_window,
                                     split_durations, split_quote_for_cards)
from scripts.cards_wide import WIDE_SIZE
from scripts.narrate import SECONDS_PER_CHAR

_R = {
    "id": "aaa", "headline": "奨学金の返済が長期化している", "category": "教育",
    "evidence": {"quote": "平均で十五年かけて返済しています。",
                 "context": "第221回国会 衆議院特別委員会 2026-05-08 谷浩一郎",
                 "source_url": "https://kokkai.ndl.go.jp/txt/1/1", "speaker": "谷浩一郎"},
}


def _recipe(tmp_path: Path, rid: str, category: str) -> None:
    (tmp_path / f"{rid}.json").write_text(json.dumps({
        "id": rid, "headline": f"{rid}の見出し", "keyword": "税",
        "category": category,
        "evidence": {"kind": "speech", "source_url": "https://kokkai.ndl.go.jp/txt/1/1",
                     "figure": "", "quote": "逐語の引用文です。", "context": "第221回国会 2026-05-08 谷浩一郎",
                     "speaker": "谷浩一郎"},
    }, ensure_ascii=False), encoding="utf-8")


def test_レシピをid順に読み込む(tmp_path):
    _recipe(tmp_path, "bbb", "税")
    _recipe(tmp_path, "aaa", "税")
    got = select_recipes(tmp_path)
    assert [r["id"] for r in got] == ["aaa", "bbb"]


def test_除外したカテゴリのレシピは入らない(tmp_path):
    """除外の値は実データに合わせて `election`。`run_election.py` が書く値で、
    `recipes/` の実測は 政治52件 / election5件。ここを架空の値（"選挙"）で
    書くと、テストは通るのに本番では1件も外れない。"""
    _recipe(tmp_path, "aaa", "政治")
    _recipe(tmp_path, "bbb", "election")
    got = select_recipes(tmp_path, exclude_categories=frozenset({"election"}))
    assert [r["id"] for r in got] == ["aaa"]


def test_除外しなければ選挙のレシピも入る(tmp_path):
    _recipe(tmp_path, "bbb", "election")
    assert len(select_recipes(tmp_path)) == 1


def test_一致しない除外指定は例外で止まる(tmp_path):
    """投票日の除外（公職選挙法129条）が綴り違いで空振りするのを防ぐ。
    警告では足りない。運用者には除外なしと同じ件数が出て、選挙関連が
    投票日を跨いで流れ続ける。"""
    _recipe(tmp_path, "aaa", "政治")
    _recipe(tmp_path, "bbb", "election")
    with pytest.raises(ExcludeCategoryNotFound, match="選挙"):
        select_recipes(tmp_path, exclude_categories=frozenset({"選挙"}))


def test_例外のメッセージに実在するカテゴリが出る(tmp_path):
    _recipe(tmp_path, "bbb", "election")
    with pytest.raises(ExcludeCategoryNotFound, match="election"):
        select_recipes(tmp_path, exclude_categories=frozenset({"選挙"}))


def test_除外で何件落ちたかを出す(tmp_path, capsys):
    """残った件数だけでは、除外が効いたのか元から0件だったのか分からない。"""
    _recipe(tmp_path, "aaa", "政治")
    _recipe(tmp_path, "bbb", "election")
    _recipe(tmp_path, "ccc", "election")
    select_recipes(tmp_path, exclude_categories=frozenset({"election"}))
    assert "- 除外 election: 2件" in capsys.readouterr().out


# ------------------------------------------------------------ 日付で決まる並び

def test_同じ日なら並びは同じ():
    recipes = [{"id": f"{i:02x}"} for i in range(20)]
    day = date(2026, 9, 9)
    assert ([r["id"] for r in shuffle_for_date(recipes, day)]
            == [r["id"] for r in shuffle_for_date(recipes, day)])


def test_日が変われば並びが変わる():
    """id は16進のハッシュなので、並べ直さないと毎日ほぼ同じ順になる
    （11.5時間のアーカイブに同じ順序の同じ内容が約17回入る）。"""
    recipes = [{"id": f"{i:02x}"} for i in range(20)]
    assert ([r["id"] for r in shuffle_for_date(recipes, date(2026, 9, 9))]
            != [r["id"] for r in shuffle_for_date(recipes, date(2026, 9, 10))])


def test_並べ替えても件数と中身は変わらない():
    recipes = [{"id": f"{i:02x}"} for i in range(20)]
    got = shuffle_for_date(recipes, date(2026, 9, 9))
    assert sorted(r["id"] for r in got) == sorted(r["id"] for r in recipes)


def test_select_recipesそのものは並べ替えない(tmp_path):
    """シャッフルは build() の仕事。選定は id 昇順で決定的に保つ。"""
    for rid in ("ccc", "aaa", "bbb"):
        _recipe(tmp_path, rid, "政治")
    assert [r["id"] for r in select_recipes(tmp_path)] == ["aaa", "bbb", "ccc"]


def test_見出しと引用と出典がこの順で入る():
    got = narration_text(_R)
    assert got.index("奨学金") < got.index("十五年") < got.index("谷浩一郎")


def test_引用は逐語のまま入る():
    assert _R["evidence"]["quote"] in narration_text(_R)


def test_引用に無い言葉を足さない():
    """台本は見出し・引用・出典の連結だけ。ここに定型の地の文を入れると、
    一次資料に無い文字列が出典付きで読み上げられることになる。"""
    got = narration_text(_R)
    for part in (_R["headline"], _R["evidence"]["quote"], _R["evidence"]["context"]):
        got = got.replace(part, "", 1)
    # 残ってよいのは区切りの句読点と空白だけ
    assert set(got) <= set("。、 \n"), f"余計な地の文が入っている: {got!r}"


def test_フレームは1920x1080():
    assert render_frame(_R).size == WIDE_SIZE


def test_引用カードに載せる文字列は一次資料の逐語(monkeypatch):
    """描画に渡した文字列が evidence.ground_excerpt を通っていること。
    通っていなければ、モデル生成値に出典が付く経路がここに開く。"""
    seen = []
    import scripts.build_live_loop as m
    original = m.ground_excerpt
    monkeypatch.setattr(m, "ground_excerpt",
                        lambda excerpt, quote: seen.append((excerpt, quote)) or original(excerpt, quote))
    render_frame(_R)
    assert seen == [(_R["evidence"]["quote"], _R["evidence"]["quote"])]


def test_尺の窓は文字数から決まる():
    text = "あ" * 200
    lo, hi = speech_window(text)
    est = 200 * SECONDS_PER_CHAR
    assert lo < est < hi


def test_短い題材でも窓が反転しない():
    lo, hi = speech_window("あ")
    assert 0 < lo < hi


def test_窓は推定尺に対して上下対称():
    """`narrate.synthesize` は窓の中央値を狙って speedScale を補正する。
    上だけ広い窓（0.70/1.40）を渡すと中央値が推定尺の1.05倍になり、
    全題材が一律に約5%遅く読まれる（ショートの声と速さが揃わない）。"""
    assert WINDOW_HIGH - 1.0 == pytest.approx(1.0 - WINDOW_LOW)
    text = "あ" * 200
    lo, hi = speech_window(text)
    est = 200 * SECONDS_PER_CHAR
    assert (lo + hi) / 2 == pytest.approx(est)


# ------------------------------------------------- 引用をカードに収まる形に分ける
#
# 実データ57件の中央値は222字で、カードに収まるのは32px・6行で約165字。
# 38件が2〜3行あふれて切り捨てられていた。ナレーションは引用を最後まで
# 読むので、切り捨てると「聞こえているのに画面に無い」状態が大半を占める。

_LONG_QUOTE = (
    "御指摘の点につきましては、現在、関係省庁と連携しながら検討を進めているところでございます。"
    "その上で申し上げますと、令和七年度の予算においては、必要な措置を講じたところであります。"
    "今後とも、実態を丁寧に把握しながら、必要な対応を検討してまいりたいと考えております。"
    "いずれにいたしましても、国民の皆様の御理解を得ながら進めることが肝要であると考えます。"
    "また、地方自治体からの御要望も踏まえ、制度の運用について改めて周知を図ってまいります。")
# 実データの引用の中央値は222字。この長さで1枚に収まらないことは
# test_長い引用は複数の枚に分かれる が縛っている。
_SOURCE = "第221回国会 衆議院予算委員会 2026-05-08 谷浩一郎"


def test_長い引用は複数の枚に分かれる():
    got = split_quote_for_cards(_LONG_QUOTE, _SOURCE)
    assert len(got) > 1


def test_分けた断片はどれも引用の連続した部分文字列():
    for piece in split_quote_for_cards(_LONG_QUOTE, _SOURCE):
        assert piece in _LONG_QUOTE


def test_つなぎ直すと元の引用に戻る():
    """省略記号も空白の詰めも入れない。1文字でも足せば、出典キャプション
    付きのカードに一次資料に無い文字列が出ることになる。"""
    assert "".join(split_quote_for_cards(_LONG_QUOTE, _SOURCE)) == _LONG_QUOTE


def test_分けた断片はどれもカードに収まる():
    from scripts.build_live_loop import _quote_overflows
    for piece in split_quote_for_cards(_LONG_QUOTE, _SOURCE):
        assert not _quote_overflows(piece, _SOURCE)


def test_カードに収まる引用は分けない():
    short = "平均で十五年かけて返済しています。"
    assert split_quote_for_cards(short, _SOURCE) == [short]


def test_句点の無い長文でも分けられる():
    """文末で切れない引用（読点だけ・区切りなし）でも、文字数で切って
    逐語のまま載せる。"""
    text = "あ" * 400
    got = split_quote_for_cards(text, _SOURCE)
    assert len(got) > 1
    assert "".join(got) == text


def test_あふれ警告を出さない(capsys):
    """1ビルドあたり38行の切り捨て警告は、無音や合成失敗という本物の
    異常をログの中に埋もれさせる（WINDOW を広げた理由と同じ）。"""
    from scripts.build_live_loop import render_frame as rf
    recipe = dict(_R, evidence=dict(_R["evidence"], quote=_LONG_QUOTE, context=_SOURCE))
    for piece in split_quote_for_cards(_LONG_QUOTE, _SOURCE):
        rf(recipe, piece)
    assert "溢れて" not in capsys.readouterr().out


def test_断片に渡した文字列も逐語の検証を通る(monkeypatch):
    seen = []
    import scripts.build_live_loop as m
    original = m.ground_excerpt
    monkeypatch.setattr(m, "ground_excerpt",
                        lambda excerpt, quote: seen.append((excerpt, quote)) or original(excerpt, quote))
    piece = _R["evidence"]["quote"][:6]
    m.render_frame(_R, piece)
    assert seen == [(piece, _R["evidence"]["quote"])]


def test_尺は断片の字数比で分ける():
    got = split_durations(["あ" * 3, "い" * 1], 8.0)
    assert got == pytest.approx([6.0, 2.0])


def test_分けた尺の合計は元の尺と一致する():
    pieces = split_quote_for_cards(_LONG_QUOTE, _SOURCE)
    assert sum(split_durations(pieces, 41.7)) == pytest.approx(41.7)


# ---------------------------------------------------------------- build()
#
# VOICEVOX と ffmpeg はどちらも重い（前者はエンジン起動・後者は実プロセス）ので、
# build() のテストでは synthesize / mix / subprocess.run だけを置き換える。
# render_frame は実物を使う（PIL の描画だけで、外部プロセスは呼ばない）。
# 置き換えた合成・mix も wave モジュールで実物の wav を書くので、
# wav_duration_seconds が読む実尺は本物のまま検証できる。

def _silence_wav(path: Path, seconds: float) -> Path:
    """外部プロセスを使わずに実尺だけ正しい wav を作る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    n_frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path


def test_buildはレシピが空だと分かるメッセージで止まる(tmp_path):
    """空リストのまま進めると frames[-1] が素の IndexError になり、
    「レシピが0件だった」という本当の原因が読み取れない。"""
    from scripts.build_live_loop import build
    with pytest.raises(ValueError, match="recipes"):
        build(tmp_path / "loop.mp4", [])


def test_buildはレシピごとに合成とmixを呼びffmpegの結合コマンドを組む(tmp_path, monkeypatch):
    import scripts.build_live_loop as m

    mix_calls = []

    def fake_synthesize(text, dest, *, target_min, target_max):
        assert target_min < target_max          # 呼び出し側が窓を渡していること
        _silence_wav(dest, 2.0)
        return dest

    def fake_mix(voice_path, out_path, *, bgm_path=None):
        mix_calls.append(Path(voice_path))
        _silence_wav(out_path, 3.0)              # mix後の実尺（BGM敷き後）

    run_calls = []

    def fake_run(cmd, **kwargs):
        run_calls.append(cmd)

    monkeypatch.setattr(m, "synthesize", fake_synthesize)
    monkeypatch.setattr(m, "mix", fake_mix)
    monkeypatch.setattr(m.subprocess, "run", fake_run)

    recipe_b = dict(_R, id="bbb")
    out_path = tmp_path / "out" / "loop.mp4"
    out = m.build(out_path, [_R, recipe_b], day=date(2026, 9, 9))

    assert out == out_path

    # BGM の関門（mix）はレシピと1対1で、全経路が必ず通る
    assert [p.name for p in mix_calls] == ["000_voice.wav", "001_voice.wav"]

    # ffmpeg は concat 2本を入力に、配信側が -c copy できる形で焼く
    assert len(run_calls) == 1
    cmd = run_calls[0]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-g") + 1] == "60"
    assert cmd[cmd.index("-keyint_min") + 1] == "60"

    work = out_path.parent / "parts"
    audio_lines = (work / "audio.txt").read_text(encoding="utf-8").splitlines()
    assert len(audio_lines) == 2   # レシピ2件ぶんの mix 済み wav

    frame_lines = (work / "frames.txt").read_text(encoding="utf-8").splitlines()
    last_png = (work / "001_00.png").as_posix()
    assert frame_lines.count(f"file '{last_png}'") == 2   # concat は最後を2度書く
    assert "duration 3.000" in frame_lines   # mix後の実尺（fake_mixが書いた3秒）がそのまま使われる


def test_buildはffmpeg失敗時に原因つきの例外にする(tmp_path, monkeypatch):
    """check=True だけに任せると失敗原因（stderr）が読み取れない。"""
    import scripts.build_live_loop as m

    def fake_synthesize(text, dest, *, target_min, target_max):
        _silence_wav(dest, 1.0)
        return dest

    def fake_mix(voice_path, out_path, *, bgm_path=None):
        _silence_wav(out_path, 1.0)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="ffmpeg boom")

    monkeypatch.setattr(m, "synthesize", fake_synthesize)
    monkeypatch.setattr(m, "mix", fake_mix)
    monkeypatch.setattr(m.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg boom"):
        m.build(tmp_path / "loop.mp4", [_R])


def test_buildは長い引用を複数フレームに分けて尺を配分する(tmp_path, monkeypatch):
    """ナレーションは引用を最後まで読む。カードに収まらないぶんを切り捨てず、
    読まれている部分が画面に出ているようにする。"""
    import scripts.build_live_loop as m

    def fake_synthesize(text, dest, *, target_min, target_max):
        _silence_wav(dest, 2.0)
        return dest

    def fake_mix(voice_path, out_path, *, bgm_path=None):
        _silence_wav(out_path, 10.0)

    run_calls = []
    monkeypatch.setattr(m, "synthesize", fake_synthesize)
    monkeypatch.setattr(m, "mix", fake_mix)
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: run_calls.append(cmd))

    recipe = dict(_R, evidence=dict(_R["evidence"], quote=_LONG_QUOTE, context=_SOURCE))
    out_path = tmp_path / "out" / "loop.mp4"
    m.build(out_path, [recipe], day=date(2026, 9, 9))

    work = out_path.parent / "parts"
    lines = (work / "frames.txt").read_text(encoding="utf-8").splitlines()
    durations = [float(ln.split()[1]) for ln in lines if ln.startswith("duration ")]
    pieces = split_quote_for_cards(_LONG_QUOTE, _SOURCE)
    assert len(durations) == len(pieces) > 1
    assert sum(durations) == pytest.approx(10.0, abs=0.01)   # mix 後の実尺
    assert (work / "000_01.png").exists()
