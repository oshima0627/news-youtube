import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from scripts.photos import attribution, is_allowed, download, MAX_IMAGE_SIZE


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


def test_download_正常に保存できる():
    """許可ホストから画像をダウンロードして保存できる。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "photo.jpg"

        mock_response = MagicMock()
        mock_response.url = "https://www.kantei.go.jp/jp/content/photo01.jpg"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_response.iter_content = lambda chunk_size: iter([b"fake image data"])

        with patch("requests.get", return_value=mock_response):
            result = download("https://www.kantei.go.jp/jp/content/photo01.jpg", dest)

            assert result["url"] == "https://www.kantei.go.jp/jp/content/photo01.jpg"
            assert "首相官邸ホームページ" in result["attribution"]
            assert result["file"] == "photo.jpg"
            assert dest.exists()
            assert dest.read_bytes() == b"fake image data"


def test_download_リダイレクト迂回を防ぐ():
    """許可ホストからの悪意のあるリダイレクトを検出する。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "photo.jpg"

        mock_response = MagicMock()
        mock_response.url = "https://www.jiji.com/photo/abc.jpg"  # 許可外へのリダイレクト
        mock_response.headers = {"content-type": "image/jpeg"}

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="リダイレクト先が許可されていません"):
                download("https://www.kantei.go.jp/jp/content/photo01.jpg", dest)


def test_download_htmlは拒否():
    """Content-Type が text/html のときは拒否する。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "photo.jpg"

        mock_response = MagicMock()
        mock_response.url = "https://www.kantei.go.jp/jp/content/photo01.jpg"
        mock_response.headers = {"content-type": "text/html"}

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="画像ではありません"):
                download("https://www.kantei.go.jp/jp/content/photo01.jpg", dest)


def test_download_サイズ上限超過():
    """ファイルサイズ上限を超えたら拒否する。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "photo.jpg"

        mock_response = MagicMock()
        mock_response.url = "https://www.kantei.go.jp/jp/content/photo01.jpg"
        mock_response.headers = {
            "content-type": "image/jpeg",
            "content-length": str(MAX_IMAGE_SIZE + 1)
        }

        with patch("requests.get", return_value=mock_response):
            with pytest.raises(ValueError, match="ファイルが大きすぎます"):
                download("https://www.kantei.go.jp/jp/content/photo01.jpg", dest)


def test_download_許可外urlではネットワークアクセスしない():
    """許可外URLを渡したら、requests.get を呼ばずに ValueError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "photo.jpg"

        with patch("requests.get") as mock_get:
            with pytest.raises(ValueError, match="取得を許可していない出所です"):
                download("https://www.jiji.com/photo/abc.jpg", dest)

            # requests.get が呼ばれていないことを確認
            mock_get.assert_not_called()
