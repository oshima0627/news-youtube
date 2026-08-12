"""画像の自動取得のテスト。

外部API（ja.wikipedia / Commons）は叩かない。判定の側だけを固定入力で確かめ、
HTTP を伴う部分は差し替える。
"""

import pytest

from scripts import commons


def _info(**kw) -> dict:
    base = dict(file="X.jpg", url="https://upload.wikimedia.org/x.jpg",
                width=1200, height=1600, mime="image/jpeg",
                license="cc-by-4.0", license_name="CC BY 4.0",
                artist="内閣官房内閣広報室", credit="", descriptionurl="")
    base.update(kw)
    return base


# --- ライセンス判定 --------------------------------------------------------

@pytest.mark.parametrize("code,name", [
    ("cc-by-4.0", "CC BY 4.0"),
    ("cc-by-sa-3.0", "CC BY-SA 3.0"),
    ("cc0", "CC0"),
    ("pd", "Public domain"),
    ("pd-japan", "PD Japan"),
])
def test_自由に使えるライセンスは通す(code, name):
    assert commons.is_free(_info(license=code, license_name=name)) is True


@pytest.mark.parametrize("code,name", [
    ("cc-by-nc-4.0", "CC BY-NC 4.0"),      # 非営利限定。広告収入のある動画で使えない
    ("cc-by-nd-4.0", "CC BY-ND 4.0"),      # 改変禁止。切り取って合成するので使えない
    ("cc-by-nc-sa-3.0", "CC BY-NC-SA 3.0"),
    ("fairuse", "Fair use"),
    ("", "Non-free"),
    ("", ""),                               # 判断できないものは通さない
])
def test_使えないライセンスは落とす(code, name):
    assert commons.is_free(_info(license=code, license_name=name)) is False


def test_ライセンスコードが空でも名前で判定する():
    # 古い記述には機械可読な License コードが入っていないものがある。
    assert commons.is_free(_info(license="", license_name="Attribution")) is True


# --- 大きさの判定 ----------------------------------------------------------

def test_拡大しすぎる画像は使わない():
    # 写真枠（1080x659）を覆うまで拡大するので、小さい画像は粗が出る。
    assert commons.is_usable(_info(width=96, height=128)) is False


def test_縦長の公式ポートレートは使える():
    # 横幅は小さいが、拡大2.1倍なら実用範囲。固定の最小幅で判定すると
    # この種の画像を落として汎用画像に落ちてしまう。
    assert commons.upscale(522, 700) < commons.MAX_UPSCALE
    assert commons.is_usable(_info(width=522, height=700)) is True


def test_画像以外は使わない():
    assert commons.is_usable(_info(mime="application/pdf")) is False
    assert commons.is_usable(_info(url="")) is False
    assert commons.is_usable(None) is False


def test_使えない大きさとライセンスは組み合わせても通らない():
    assert commons.is_usable(_info(license="cc-by-nc-4.0",
                                   license_name="CC BY-NC 4.0")) is False


# --- 発言者から画像を決める ------------------------------------------------

def test_発言者の記事画像を優先する(monkeypatch):
    calls: list[str] = []

    def fake_find(article):
        calls.append(article)
        return _info() if article == "片山さつき" else None

    monkeypatch.setattr(commons, "find_image", fake_find)

    got = commons.resolve("片山さつき")

    assert got is not None
    assert got["article"] == "片山さつき"
    assert got["is_fallback"] is False
    assert calls == ["片山さつき"]          # 見つかったら汎用画像は引かない


def test_発言者の画像が無ければ汎用画像に落とす(monkeypatch):
    # 政府参考人など、記事はあっても画像が無い発言者は実際に出る（実測: 谷滋行）。
    # ここで諦めると、根拠が取れているのに画像だけの理由で題材を捨てることになる。
    monkeypatch.setattr(commons, "find_image",
                        lambda a: _info() if a == commons.FALLBACK_ARTICLE else None)

    got = commons.resolve("谷滋行")

    assert got is not None
    assert got["article"] == commons.FALLBACK_ARTICLE
    assert got["is_fallback"] is True


def test_発言者が空でも汎用画像で作れる(monkeypatch):
    monkeypatch.setattr(commons, "find_image",
                        lambda a: _info() if a == commons.FALLBACK_ARTICLE else None)

    got = commons.resolve("")

    assert got is not None
    assert got["is_fallback"] is True


def test_発言者の検索が例外で落ちても汎用画像を試す(monkeypatch):
    # 片方の記事で通信が落ちただけで、その日の題材を捨てる理由にはならない。
    def flaky(article):
        if article != commons.FALLBACK_ARTICLE:
            raise RuntimeError("接続できません")
        return _info()

    monkeypatch.setattr(commons, "find_image", flaky)

    got = commons.resolve("片山さつき")

    assert got is not None
    assert got["is_fallback"] is True


def test_どちらも取れなければNoneを返す(monkeypatch):
    monkeypatch.setattr(commons, "find_image", lambda a: None)

    assert commons.resolve("片山さつき") is None


def test_find_imageは使えない画像を返さない(monkeypatch):
    monkeypatch.setattr(commons, "lead_image_file", lambda a: "Tiny.jpg")
    monkeypatch.setattr(commons, "image_info",
                        lambda f, width=commons.THUMB_WIDTH: _info(width=96, height=128))

    assert commons.find_image("誰か") is None


# --- 出典表記 --------------------------------------------------------------

def test_出典表記に作者とライセンス名と出所を出す():
    # CC は作者とライセンスの表示を義務づけている。URLだけでは足りない。
    got = commons.credit(_info(
        artist="内閣官房内閣広報室", license_name="CC BY 4.0",
        descriptionurl="https://commons.wikimedia.org/wiki/File:X.jpg"))

    assert "内閣官房内閣広報室" in got
    assert "CC BY 4.0" in got
    assert "https://commons.wikimedia.org/wiki/File:X.jpg" in got


def test_作者が取れなくても出典表記は作れる():
    got = commons.credit(_info(artist="", credit="", license_name="CC0"))

    assert "CC0" in got
    assert got.strip()


def test_作者名のHTMLは取り除く():
    # extmetadata の Artist はリンクつきHTMLで返る。そのまま概要欄に出すと
    # タグが見えてしまう。
    got = commons._strip_html(
        '<a href="//commons.wikimedia.org/wiki/User:Kakidai">Kakidai</a>')

    assert got == "Kakidai"
