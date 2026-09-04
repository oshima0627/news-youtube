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


def test_許可リストは両候補を同じ数だけ持つ():
    # 片方だけになっていたら、この経路は一方の候補の宣伝装置になる。
    # 「要約ページは両方あるが、詳しい政策集は片方だけ」も同じことなので、
    # 候補ごとの**件数が揃っている**ことまで縛る。
    from collections import Counter
    per_person = Counter(s.person for s in election.MANIFESTO_SOURCES.values())
    assert len(per_person) == 2, "両候補ぶん揃っていない"
    assert len(set(per_person.values())) == 1, f"候補ごとの資料数が不揃い: {per_person}"


def test_要約ページと政策集が両候補ぶんある():
    assert {KOJA, TAMAKI, "koja-detail", "tamaki-detail"} <= set(
        election.MANIFESTO_SOURCES)


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


# --- PDF の政策集 ---------------------------------------------------------

def test_テキスト層の無いPDFは一次資料に使わない():
    # 画像だけのPDFを通すと、逐語照合が「一致しない」ではなく
    # 「照合対象が無い」状態になり、この経路唯一の関門が無効になる。
    import io
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(election.SourceUnreadable):
        election._pdf_text(buf.getvalue())


def test_政策集のURLはPDFを指している():
    for key in ("koja-detail", "tamaki-detail"):
        assert election.MANIFESTO_SOURCES[key].url.lower().endswith(".pdf")


def test_文字化けした抽出結果は一次資料に使わない():
    # 埋め込みフォントに ToUnicode マッピングが無いPDFは、文字数だけは
    # 取れるので MIN_PDF_CHARS を通ってしまう。玉城氏の政策集PDFで実際に踏んだ。
    garbled = "৓σχʔ" * 300
    with pytest.raises(election.SourceUnreadable):
        election._assert_readable(garbled, "https://example.invalid/x.pdf")


def test_日本語として読める資料は通る():
    ok = "沖縄県知事選挙に立候補している候補者が公表している政策です。" * 20
    assert election._assert_readable(ok, "https://example.invalid/x.html") == ok


# ── 説明文（run_election.write_meta） ──────────────────────────────
#
# 説明文は動画ごとに1回だけ書かれ、投稿後は誰も読み返さない。ここが
# 崩れても動画は普通に出来上がるので、テストで縛っていないと気づけない。

def _description(tmp_path, monkeypatch):
    """write_meta が書いた description.txt を読む。"""
    from scripts import run_election

    class _Script:
        title, tags, narration = "題名", ["a", "b", "c"], "本文"

    class _Ev:
        source_url = election.MANIFESTO_SOURCES[KOJA].url
        context = "古謝玄太 公約"

    run_election.write_meta(tmp_path, _Script(), {"attribution": "画像: x"}, _Ev())
    return (tmp_path / "description.txt").read_text(encoding="utf-8")


def test_説明文は候補者を1人1行にする(tmp_path, monkeypatch):
    # MANIFESTO_SOURCES は1人につき複数（要約ページと政策集PDF）を持つ。
    # そのまま並べると同じ人が2回出て、何人が候補なのか読み取れなくなる。
    from scripts import election as el

    text = _description(tmp_path, monkeypatch)
    for person in {s.person for s in el.MANIFESTO_SOURCES.values()}:
        assert text.count(f"・{person}: ") == 1, f"{person} が1行になっていない"


def test_説明文に届け出者数を書く(tmp_path, monkeypatch):
    # 公式サイトのリンクが2人ぶんしか無いので、書かないと「候補は2人」と
    # 読める。実際の届け出は6人（2026-08-27 告示）。
    from scripts import run_election

    text = _description(tmp_path, monkeypatch)
    assert f"{run_election.CANDIDATE_COUNT}人が立候補" in text
    assert run_election.CANDIDATE_COUNT > len(
        {s.person for s in election.MANIFESTO_SOURCES.values()})
