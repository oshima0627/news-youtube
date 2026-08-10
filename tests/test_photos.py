import pytest

from scripts.photos import attribution, is_allowed


@pytest.mark.parametrize("url", [
    "https://www.kantei.go.jp/jp/content/photo01.jpg",
    "https://www.mod.go.jp/j/press/photo/2026/a.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/1/12/Takaichi.jpg",
])
def test_許可された出所は通る(url):
    assert is_allowed(url) is True


@pytest.mark.parametrize("url", [
    "https://www.jiji.com/photo/abc.jpg",         # 報道機関
    "https://www.asahi.com/images/x.jpg",
    "https://example.com/kantei.go.jp/fake.jpg",  # パスに紛れ込ませた偽装
    "http://www.kantei.go.jp/photo.jpg",          # httpは受けない
    "https://kantei.go.jp.evil.com/photo.jpg",    # サブドメイン偽装
    "",
])
def test_許可されていない出所は弾く(url):
    assert is_allowed(url) is False


def test_官邸は出典と加工の記載を出す():
    got = attribution("https://www.kantei.go.jp/jp/content/photo01.jpg")
    assert "首相官邸ホームページ" in got
    assert "加工" in got


def test_コモンズはクレジットを出す():
    got = attribution("https://upload.wikimedia.org/wikipedia/commons/1/12/A.jpg")
    assert "Wikimedia Commons" in got
