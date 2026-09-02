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


def test_downloadはUser_Agentを名乗る(tmp_path, monkeypatch):
    # Wikimedia は既定の python-requests の User-Agent を 403 で拒否する。
    # 名乗らないと画像だけが毎回落とせず、原因が「403」としか出ない。
    # <https://meta.wikimedia.org/wiki/User-Agent_policy>
    from scripts import photos

    captured: dict = {}

    class _Resp:
        url = "https://upload.wikimedia.org/x.jpg"
        headers = {"content-type": "image/jpeg", "content-length": "9"}

        def raise_for_status(self): pass
        def iter_content(self, chunk_size=8192): yield b"jpegbytes"

    def fake_get(url, timeout=None, stream=None, headers=None):
        captured["headers"] = headers or {}
        return _Resp()

    monkeypatch.setattr(photos.requests, "get", fake_get)

    photos.download("https://upload.wikimedia.org/x.jpg", tmp_path / "p.jpg")

    assert captured["headers"].get("User-Agent") == photos.USER_AGENT
    assert "python-requests" not in captured["headers"].get("User-Agent", "")


def test_downloadは渡された出典表記を使う(tmp_path, monkeypatch):
    # Wikimedia の画像は作者とライセンス名の表示が必要で、URLだけの
    # 既定表記では足りない。取得元のメタデータを持つ側から渡す。
    from scripts import photos

    class _Resp:
        url = "https://upload.wikimedia.org/x.jpg"
        headers = {"content-type": "image/jpeg"}

        def raise_for_status(self): pass
        def iter_content(self, chunk_size=8192): yield b"jpegbytes"

    monkeypatch.setattr(photos.requests, "get",
                        lambda url, timeout=None, stream=None, headers=None: _Resp())

    rec = photos.download("https://upload.wikimedia.org/x.jpg", tmp_path / "p.jpg",
                          credit="画像: 内閣官房内閣広報室 / CC BY 4.0（https://x）")

    assert rec["attribution"] == "画像: 内閣官房内閣広報室 / CC BY 4.0（https://x）"


# --- Wikimedia のサムネイル配信ホスト -------------------------------------
# commons の imageinfo は thumb.wikimedia.org を返すことがある
# （upload.wikimedia.org と同じ内容を配る Wikimedia 自身のホスト）。
# 許可リストに無かったため、そのホストが返った題材は download が
# ValueError を投げ、run_daily 側で「画像を取得できません」として
# **題材ごと見送られていた**（フォールバックもしない）。
# 2026-09-02 に 玉城デニー の記事画像で実際に踏んだ。

def test_wikimedia_のサムネイルホストも通る():
    assert is_allowed(
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/57/"
        "Denny_Tamaki.jpg/1280px-Denny_Tamaki.jpg") is True


def test_wikimedia_を騙るホストは通さない():
    assert is_allowed("https://thumb.wikimedia.org.evil.com/x.jpg") is False
    assert is_allowed("https://evil-thumb.wikimedia.org.co/x.jpg") is False


def test_サムネイルホストの出典表記も_commons_扱いになる():
    # 汎用の分岐に落ちると「出典: thumb.wikimedia.org」という、
    # クレジットとして意味をなさない表記が説明欄に出る。
    url = ("https://thumb.wikimedia.org/wikipedia/commons/thumb/5/57/"
           "Denny_Tamaki.jpg/1280px-Denny_Tamaki.jpg")
    assert attribution(url) == f"画像: Wikimedia Commons（{url}）"
