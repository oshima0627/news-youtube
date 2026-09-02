from PIL import Image, ImageDraw

from scripts import draw as draw_module
from scripts.draw import fit_font, pick_font, wrap


def _draw():
    return ImageDraw.Draw(Image.new("RGB", (10, 10)))


def test_wrapは改行を空白に正規化してから折り返す():
    # textbboxは\nを含む文字列を複数行として測定するため、正規化しないと
    # 幅の判定がズレる。改行入りと、事前に空白へ置換したものとで
    # 同じ折り返し結果になることを確認する。
    d = _draw()
    f = pick_font(40)
    with_newline = wrap(d, "あいう\nえお", f, 10_000)
    pre_normalized = wrap(d, "あいう えお", f, 10_000)
    assert with_newline == pre_normalized


def test_fit_fontは改行を空白に正規化してから幅を測る():
    d = _draw()
    with_newline = fit_font(d, "あ\nい", 200, 92)
    pre_normalized = fit_font(d, "あ い", 200, 92)
    assert with_newline.size == pre_normalized.size


def test_日本語フォントが全滅したら警告を出す(monkeypatch, capsys):
    # 警告が無いと、文字がすべて豆腐（□）になった動画が完全自動で
    # そのまま公開され、誰も気づかない
    monkeypatch.setattr(draw_module, "FONT_SANS", [r"C:\存在しない\font.ttc"])
    monkeypatch.setattr(draw_module, "_warned_no_font", False)

    pick_font(40)

    out = capsys.readouterr().out
    assert "日本語フォント" in out
    assert "豆腐" in out


def test_フォント全滅の警告は一度しか出さない(monkeypatch, capsys):
    # pick_font は1フレームあたり何十回も呼ばれる。毎回出すと他の警告が埋もれる
    monkeypatch.setattr(draw_module, "FONT_SANS", [r"C:\存在しない\font.ttc"])
    monkeypatch.setattr(draw_module, "_warned_no_font", False)

    for _ in range(5):
        pick_font(40)

    assert capsys.readouterr().out.count("日本語フォント") == 1


# --- 漢数字の表記直し --------------------------------------------------------
#
# 国会会議録は数字を漢字で書き起こす。そのまま画面に出すと「一〇％」
# 「千六百三十億円」になって読めないので算用数字に直す。ただし
# **読みやすさより壊さないことが優先**で、数量かどうか判断できない並びは
# そのまま残す（「一部」を「1部」に、「九州」を「9州」にしてはいけない）。

import pytest

from scripts.draw import normalize_numerals


@pytest.mark.parametrize("src,want", [
    # 位取り式
    ("肉、魚は一〇％なんですよ", "肉、魚は10%なんですよ"),
    ("基本的な食料品は四％", "基本的な食料品は4%"),
    ("二〇二六年度の予算", "2026年度の予算"),
    ("標準税率は二〇になっている", "標準税率は20になっている"),
    # 小数点（中黒）
    ("減収額が約四・三兆円", "減収額が約4.3兆円"),
    # 命数法。万・億・兆は単位として残す（163000000000 では読めない）
    ("詐欺被害が千六百三十億円に上り", "詐欺被害が1630億円に上り"),
    ("三十四兆三千七十七億円の利益", "34兆3077億円の利益"),
    ("過去最多の約四百十三万人", "過去最多の約413万人"),
    ("最低賃金千五百円への引上げ", "最低賃金1500円への引上げ"),
    ("口座数が二千八百万に達する", "口座数が2800万に達する"),
    ("議員定数を四十五削減する", "議員定数を45削減する"),
])
def test_漢数字を算用数字に直す(src, want):
    assert normalize_numerals(src) == want


@pytest.mark.parametrize("src", [
    "一部の議員が反対した",     # 部・方・体などは助数詞ではない
    "一方で政府は",
    "一時的な措置",
    "一体改革",
    "一般会計",
    "一律に扱う",
    "十分に議論する",           # じゅうぶん。「10分」にしてはいけない
    "万一の事態に備える",       # 大きい単位で始まる並びは数ではない
    "九州地方",                 # 州は助数詞ではない
    "千葉県",
    "百貨店",
    "第三者委員会",
])
def test_数量でない並びは変えない(src):
    assert normalize_numerals(src) == src


def test_出典キャプションは変わらない():
    text = "第221回国会 参議院財政金融委員会 片山さつき"
    assert normalize_numerals(text) == text


def test_値は変わらない():
    # 表記を変える処理であって、数を作り替える処理ではない。
    assert normalize_numerals("三十四兆三千七十七億円") == "34兆3077億円"
    assert normalize_numerals("四百十三万人") == "413万人"


def test_値が0になる単位は出力しない():
    # 「一兆万」のような壊れた並びでも「1兆0万」を作らない。regex は
    # 漢数字の連なりを機械的に拾うので、意味を成さない並びも入ってくる。
    assert normalize_numerals("一兆万") == "1兆"


def test_句点は行頭に落とさない():
    # 禁則処理。テロップで「魚は10パーセントだと説明しました」の次の行が
    # 「。」1文字だけになるのが実際に起きた。
    from PIL import Image, ImageDraw

    from scripts.draw import pick_font, wrap

    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = pick_font(58)
    body = "あいうえお"
    # ちょうど本文だけが収まり、次の「。」が溢れる幅にする
    box = d.textbbox((0, 0), body, font=font)
    width = box[2] - box[0]

    got = wrap(d, body + "。", font, width)

    assert got == ["あいうえお。"], got


def test_閉じ括弧も行頭に落とさない():
    from PIL import Image, ImageDraw

    from scripts.draw import pick_font, wrap

    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = pick_font(58)
    body = "「あいうえお"
    box = d.textbbox((0, 0), body, font=font)

    got = wrap(d, body + "」", font, box[2] - box[0])

    assert got == ["「あいうえお」"], got


def test_英数字は途中で折り返さない():
    # 1文字ずつ送ると見出しの「G7」が「G」／「7」に割れる（実際に起きた）。
    from PIL import Image, ImageDraw

    from scripts.draw import pick_font, wrap

    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = pick_font(58)
    head = "食料品の軽減、"
    width = d.textbbox((0, 0), head + "G", font=font)[2]

    got = wrap(d, head + "G7では", font, width)

    assert got[0] == head
    assert got[1].startswith("G7")


def test_パーセントも数字から離れない():
    from PIL import Image, ImageDraw

    from scripts.draw import pick_font, wrap

    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = pick_font(58)
    head = "税率は"
    width = d.textbbox((0, 0), head + "1", font=font)[2]

    got = wrap(d, head + "10%です", font, width)

    assert "10%" in got[1]


# --- 改行位置の自然さ -----------------------------------------------------
# 幅だけで折り返していた頃は、実測158か所のうち36%が語の途中で割れていた
# （「してい」／「る」、「辺野古移」／「設」、「231万」／「5000円」）。
# 数値＋単位をひとかたまりにし、句読点・かっこ・助詞・ひらがな→漢字の
# 変わり目まで戻して切るようにして5%まで下げた。

def _wrap(text: str, max_w: int) -> list[str]:
    from PIL import Image, ImageDraw
    from scripts.draw import pick_font, wrap
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    return wrap(d, text, pick_font(66), max_w)


def test_数値と単位は行をまたがない():
    # 「231万」／「5000円」に割れると、行をまたいだ数字が別の額に読める。
    for text in ["ひとりあたり県民所得231万5000円をふやします",
                 "観光収入1兆747億円を2兆円にふやすとしています"]:
        for line in _wrap(text, 700):
            assert not line.endswith(("231万", "1兆747", "552", "1兆")), line


def test_句読点の直後で切る():
    lines = _wrap("二つ目は子育て。沖縄県こども未来部の予算を見ます。", 620)
    assert lines[0].endswith("。")


def test_助詞やひらがなの直後で切り語の途中では切らない():
    lines = _wrap("沖縄県知事選挙に立候補している古謝玄太氏の政策です。", 620)
    # 「立候補してい」／「る」のような割れ方をしない
    assert not lines[0].endswith("してい")
    assert not lines[1].startswith("る")


def test_戻しすぎて極端に短い行を作らない():
    text = "沖縄県知事選挙に立候補している候補者の政策をここで詳しく読みます。"
    lines = _wrap(text, 700)
    longest = max(len(x) for x in lines)
    for line in lines[:-1]:                 # 最終行は余りなので除く
        assert len(line) >= longest * 0.5, (line, lines)


def test_英数字の連なりは従来どおり割れない():
    for line in _wrap("G7の食料品税率は10%でした", 200):
        assert line not in ("G", "7", "1", "0%")


def test_行頭禁則は維持される():
    from scripts.draw import _NO_LINE_START
    for line in _wrap("これは試験です。次の文もあります。さらに続きます。", 300)[1:]:
        assert line[0] not in _NO_LINE_START, line


def test_括弧の中では折らない():
    # 引用は1つのまとまり。途中で切ると読み手が繋ぎ直すことになる
    # （hiroyuki-youtube が 2026-08-14 に同じ問題を踏んでいる）。
    lines = _wrap("返ってくるのは「場所を変えるか、順序を変えるか」でした。", 900)
    assert lines[0] == "返ってくるのは", lines
