"""チャンネル取り違えガード（assert_expected_channel / current_channel）と
set_privacy の単体テスト。

認証を伴う実チャンネル確認（--auth-only）はオーナー操作のためスキップしているが、
`service` をモックすればガードのロジック自体は検証できる。誤ったチャンネルに
アップロードする事故を上げる前に止める、というこのパイプライン最大の安全弁なので、
経路を1つずつ潰しておく。
"""

from __future__ import annotations

import pytest

from scripts import upload_youtube as uy


class _ChannelsList:
    def __init__(self, items=None):
        self._items = items if items is not None else []

    def execute(self):
        return {"items": self._items}


class _FakeChannels:
    def __init__(self, items=None):
        self._items = items

    def list(self, part, mine):
        return _ChannelsList(self._items)


class _FakeService:
    """current_channel が使う service.channels().list(...).execute() だけを実装する。"""

    def __init__(self, items=None):
        self._channels = _FakeChannels(items)

    def channels(self):
        return self._channels


def _http_error():
    """googleapiclient.errors.HttpError の実インスタンスを最小限の resp/content で作る。"""
    from googleapiclient.errors import HttpError

    class _FakeResp:
        status = 403
        reason = "Forbidden"

    return HttpError(resp=_FakeResp(), content=b'{"error": {"message": "forbidden"}}')


def _channel_item(channel_id: str, title: str) -> dict:
    return {"id": channel_id, "snippet": {"title": title}}


EXPECTED_ID = "UCYHTfHJOoETzvpx-VZlUTng"
EXPECTED_TITLE = "日本の最新ニュースまるわかり"


# --- current_channel ---------------------------------------------------

def test_current_channelはitemsの先頭からidとtitleを返す():
    service = _FakeService(items=[_channel_item(EXPECTED_ID, EXPECTED_TITLE)])
    ch = uy.current_channel(service)
    assert ch == {"id": EXPECTED_ID, "title": EXPECTED_TITLE}


def test_current_channelはitemsが空ならNoneを返す():
    service = _FakeService(items=[])
    assert uy.current_channel(service) is None


def test_current_channelはHttpErrorのときNoneを返す(capsys):
    class _RaisingList:
        def execute(self):
            raise _http_error()

    class _RaisingChannels:
        def list(self, part, mine):
            return _RaisingList()

    class _RaisingService:
        def channels(self):
            return _RaisingChannels()

    assert uy.current_channel(_RaisingService()) is None
    assert "チャンネルを確認できませんでした" in capsys.readouterr().out


# --- assert_expected_channel --------------------------------------------

def test_expected_channel_idが無いときは終了する():
    service = _FakeService(items=[_channel_item(EXPECTED_ID, EXPECTED_TITLE)])
    meta = {"id": "x", "title": "t"}  # expected_channel_id なし
    with pytest.raises(SystemExit):
        uy.assert_expected_channel(service, meta)


def test_expected_channel_idが空文字のときは終了する():
    service = _FakeService(items=[_channel_item(EXPECTED_ID, EXPECTED_TITLE)])
    meta = {"id": "x", "title": "t", "expected_channel_id": ""}
    with pytest.raises(SystemExit):
        uy.assert_expected_channel(service, meta)


# --- 取り違えは専用の終了コードで返す（run_daily.py がこれで環境不備と判断する） ---

def test_チャンネル不一致は専用の終了コード3で終了する():
    # 汎用の1だと run_daily.py 側が ffmpeg 失敗や一時的なAPIエラーと区別できず、
    # 全候補で同じ失敗を繰り返した末に終了コード0の「本日 0/2 本」になる
    other = _FakeService(items=[_channel_item("UCwrong", "別のチャンネル")])
    meta = {"id": "x", "title": "t", "expected_channel_id": EXPECTED_ID}

    with pytest.raises(SystemExit) as exc_info:
        uy.assert_expected_channel(other, meta)

    assert exc_info.value.code == uy.EXIT_CHANNEL_MISMATCH == 3


def test_expected_channel_idが無いときも終了コード3で終了する():
    service = _FakeService(items=[_channel_item(EXPECTED_ID, EXPECTED_TITLE)])
    with pytest.raises(SystemExit) as exc_info:
        uy.assert_expected_channel(service, {"id": "x", "title": "t"})

    assert exc_info.value.code == uy.EXIT_CHANNEL_MISMATCH


def test_取り違え以外のdieは従来どおり終了コード1のまま():
    # 取り違え専用コードを他の失敗にまで広げると、run_daily.py が
    # 題材固有の失敗まで環境不備として中止してしまう
    with pytest.raises(SystemExit) as exc_info:
        uy.die("なんらかの失敗")

    assert exc_info.value.code == 1


def test_チャンネルIDが一致しないときは終了しメッセージに期待値と実際の値が入る(capsys):
    other_id = "UCwrongwrongwrongwrongwrong"
    other_title = "別のチャンネル"
    service = _FakeService(items=[_channel_item(other_id, other_title)])
    meta = {"id": "x", "title": "t", "expected_channel_id": EXPECTED_ID}

    with pytest.raises(SystemExit):
        uy.assert_expected_channel(service, meta)

    err = capsys.readouterr().err
    assert EXPECTED_ID in err  # 期待値
    assert other_id in err     # 実際の値
    assert other_title in err


def test_current_channelがNoneのときは終了する(capsys):
    service = _FakeService(items=[])  # current_channel は None を返す
    meta = {"id": "x", "title": "t", "expected_channel_id": EXPECTED_ID}

    with pytest.raises(SystemExit):
        uy.assert_expected_channel(service, meta)

    err = capsys.readouterr().err
    assert EXPECTED_ID in err
    assert "取得できず" in err


def test_一致するときだけ通過してチャンネル情報を返す():
    service = _FakeService(items=[_channel_item(EXPECTED_ID, EXPECTED_TITLE)])
    meta = {"id": "x", "title": "t", "expected_channel_id": EXPECTED_ID}

    ch = uy.assert_expected_channel(service, meta)

    assert ch == {"id": EXPECTED_ID, "title": EXPECTED_TITLE}


# --- set_privacy ----------------------------------------------------------

class _FakeVideosList:
    def __init__(self, status: dict):
        self._status = status

    def execute(self):
        return {"items": [{"status": self._status}]}


class _FakeVideosUpdate:
    def __init__(self, calls: list):
        self._calls = calls

    def execute(self):
        return {}


class _FakeVideos:
    def __init__(self, current_status: dict, calls: list):
        self._current_status = current_status
        self._calls = calls

    def list(self, part, id):
        return _FakeVideosList(self._current_status)

    def update(self, part, body):
        self._calls.append(body)
        return _FakeVideosUpdate(self._calls)


class _FakeServiceForPrivacy:
    def __init__(self, current_status: dict):
        self.calls: list = []
        self._videos = _FakeVideos(current_status, self.calls)

    def videos(self):
        return self._videos


def test_set_privacyはpublish_at指定時にprivateのままpublishAtを送る():
    current_status = {"selfDeclaredMadeForKids": False, "license": "youtube"}
    service = _FakeServiceForPrivacy(current_status)

    uy.set_privacy(service, "vid123", "public", publish_at="2026-08-12T07:30:00+09:00")

    assert len(service.calls) == 1
    body = service.calls[0]
    assert body["id"] == "vid123"
    # public と同時に送ると予約が無視されて即時公開になるため、
    # publish_at 指定時は必ず private のまま送る
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-08-12T07:30:00+09:00"


def test_set_privacyはpublish_at無しならprivacyをそのまま送る():
    current_status = {"selfDeclaredMadeForKids": False}
    service = _FakeServiceForPrivacy(current_status)

    uy.set_privacy(service, "vid123", "public")

    body = service.calls[0]
    assert body["status"]["privacyStatus"] == "public"
    assert "publishAt" not in body["status"]


def test_set_privacyは現在のstatusを読んでから書き戻す():
    # videos.update は part を丸ごと置き換えるため、既存の書き込み可能項目
    # （license / embeddable / publicStatsViewable / selfDeclaredMadeForKids）
    # を保持したまま status を送っていることを確認する
    current_status = {
        "selfDeclaredMadeForKids": True,
        "license": "creativeCommon",
        "embeddable": False,
        "publicStatsViewable": True,
        "uploadStatus": "processed",  # 読み取り専用。送り返すとエラーになるので含めない
    }
    service = _FakeServiceForPrivacy(current_status)

    uy.set_privacy(service, "vid123", "private")

    body = service.calls[0]
    status = body["status"]
    assert status["selfDeclaredMadeForKids"] is True
    assert status["license"] == "creativeCommon"
    assert status["embeddable"] is False
    assert status["publicStatsViewable"] is True
    assert "uploadStatus" not in status


def test_set_privacyは動画が見つからないときは終了する():
    class _EmptyVideosList:
        def execute(self):
            return {"items": []}

    class _EmptyVideos:
        def list(self, part, id):
            return _EmptyVideosList()

    class _S:
        def videos(self):
            return _EmptyVideos()

    with pytest.raises(SystemExit):
        uy.set_privacy(_S(), "missing_vid", "public")
