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


def _raising_service(error):
    class _RaisingList:
        def execute(self):
            raise error

    class _RaisingChannels:
        def list(self, part, mine):
            return _RaisingList()

    class _RaisingService:
        def channels(self):
            return _RaisingChannels()

    return _RaisingService()


def test_チャンネルを確認できなかったときは取り違えと別の終了コードで止まる(capsys):
    """None を返して取り違えガードに任せると、**別チャンネル**と同じ扱いになる。

    実測 2026-08-14: クォータ超過（403 quotaExceeded）で channels.list が
    落ちた結果、「アップロード先のチャンネルが指定と一致しません／実際: 取得
    できず」と表示され、対処として token.json の削除を促した。正常なトークンを
    捨てさせるうえ、クォータは1つも回復しない。
    """
    with pytest.raises(SystemExit) as e:
        uy.current_channel(_raising_service(_http_error()))

    assert e.value.code == uy.EXIT_CHANNEL_UNVERIFIED == 4
    err = capsys.readouterr().err
    assert "確認できませんでした" in err
    assert "一致しません" not in err          # 取り違えとは言わない
    assert "削除" not in err                  # token.json を捨てさせない


def test_クォータ超過のときは待てば直ることとリセット時刻を出す(capsys):
    """原因が分からないと、正しいトークンを消す方向に手が動く。"""
    from googleapiclient.errors import HttpError

    class _FakeResp:
        status = 403
        reason = "Forbidden"

    # 実際に返ってきた応答と同じ形（2026-08-14 の channels.list）。
    quota_error = HttpError(resp=_FakeResp(), content=(
        b'{"error": {"code": 403, "message": "The request cannot be completed'
        b' because you have exceeded your quota.", "errors": [{"message":'
        b' "quota", "domain": "youtube.quota", "reason": "quotaExceeded"}]}}'))

    with pytest.raises(SystemExit) as e:
        uy.current_channel(_raising_service(quota_error))

    assert e.value.code == uy.EXIT_CHANNEL_UNVERIFIED
    err = capsys.readouterr().err
    assert "クォータ" in err
    assert "リセット" in err
    assert "消さないこと" in err


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


def test_アカウントにチャンネルが1つも無いときは終了する(capsys):
    # current_channel が None を返すのはこの場合だけ（確認できなかったときは
    # current_channel 側が EXIT_CHANNEL_UNVERIFIED で止める）。
    service = _FakeService(items=[])
    meta = {"id": "x", "title": "t", "expected_channel_id": EXPECTED_ID}

    with pytest.raises(SystemExit) as e:
        uy.assert_expected_channel(service, meta)

    assert e.value.code == uy.EXIT_CHANNEL_MISMATCH
    err = capsys.readouterr().err
    assert EXPECTED_ID in err
    assert "チャンネルが1つもありません" in err


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


# --- token.json が失効しているときの経路 -------------------------------------
#
# 2026-08-26 に、失効した token.json を持ったまま `--auth-only` を叩くと
# `creds.refresh()` が RefreshError を投げて、**その下の同意画面フローに
# 落ちてこない**ことが分かった（known-issues 14番）。復旧手段が
# 「token.json を手で消す」しか無くなるうえ、9番の「消すな」という指示と
# 見分けが付かない。失効は refresh では戻らないので、同意画面へ落とす。


class _DeadCreds:
    """refresh すると RefreshError を投げる、失効済みトークンの代わり。"""

    expired = True
    refresh_token = "dead"
    valid = False

    def __init__(self, exc):
        self._exc = exc
        self.refresh_called = 0

    def refresh(self, request):
        self.refresh_called += 1
        raise self._exc


class _LiveCreds:
    expired = False
    refresh_token = "live"
    valid = True

    def to_json(self):
        return '{"token": "new"}'


def _patch_google(monkeypatch, tmp_path, creds_from_file, flow_result):
    """get_service が関数内で import する google 系を差し替える。

    実物のモジュールに monkeypatch を当てる（未導入の環境では importorskip
    でスキップする）。戻り値は「同意画面フローが何回呼ばれたか」を数えるリスト。
    """
    credentials = pytest.importorskip("google.oauth2.credentials")
    flow_mod = pytest.importorskip("google_auth_oauthlib.flow")
    discovery = pytest.importorskip("googleapiclient.discovery")

    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    secret = tmp_path / "client_secret.json"
    secret.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(uy, "TOKEN", token)
    monkeypatch.setattr(uy, "CLIENT_SECRET", secret)

    monkeypatch.setattr(credentials.Credentials, "from_authorized_user_file",
                        staticmethod(lambda *a, **k: creds_from_file))

    flow_calls = []

    class _FakeFlow:
        def run_local_server(self, port):
            flow_calls.append(port)
            return flow_result

    monkeypatch.setattr(flow_mod.InstalledAppFlow, "from_client_secrets_file",
                        staticmethod(lambda *a, **k: _FakeFlow()))
    monkeypatch.setattr(discovery, "build", lambda *a, **k: "service")
    return flow_calls, token


def test_失効したtokenは同意画面をやり直す(monkeypatch, tmp_path, capsys):
    exceptions = pytest.importorskip("google.auth.exceptions")
    dead = _DeadCreds(exceptions.RefreshError(
        "invalid_grant: Token has been expired or revoked.",
        {"error": "invalid_grant"}))
    flow_calls, token = _patch_google(monkeypatch, tmp_path, dead, _LiveCreds())

    assert uy.get_service() == "service"

    assert dead.refresh_called == 1
    assert len(flow_calls) == 1, "同意画面フローに落ちていない"
    assert token.read_text(encoding="utf-8") == '{"token": "new"}'
    # なぜやり直したのかが画面に出ていないと、9番（クォータ超過）と区別できない
    out = capsys.readouterr().out
    assert "invalid_grant" in out


def test_生きているtokenは同意画面をやり直さない(monkeypatch, tmp_path):
    live = _LiveCreds()
    flow_calls, _ = _patch_google(monkeypatch, tmp_path, live, _LiveCreds())

    assert uy.get_service() == "service"

    assert flow_calls == [], "生きているトークンで同意画面を開いている"


# ── --publish-id（workdir が残っていない動画を公開に戻す） ──────────
#
# work/ を掃除したあとの動画は `upload_youtube.py <workdir> --publish` を
# 使えない（meta.json が無い）。かといって state/published.json を手で
# 直すのは禁止（CLAUDE.md）。video_id を入口にして、記録の更新まで
# 同じ経路を通す。

import json  # noqa: E402


def _published(tmp_path, entries: dict):
    path = tmp_path / "published.json"
    path.write_text(json.dumps({"videos": entries}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _entry(video_id: str, channel_id: str = EXPECTED_ID, privacy: str = "private",
           publish_at: str | None = None) -> dict:
    e = {"youtube_video_id": video_id,
         "url": f"https://www.youtube.com/watch?v={video_id}",
         "title": "記録済みの動画", "privacy_status": privacy,
         "channel_id": channel_id}
    if publish_at:
        e["publish_at"] = publish_at
    return e


def _run_publish_id(monkeypatch, tmp_path, entries, video_id, items=None):
    """--publish-id の経路だけを動かす。認証とAPIはモックする。"""
    path = _published(tmp_path, entries)
    monkeypatch.setattr(uy, "PUBLISHED", path)
    monkeypatch.setattr(uy, "get_service",
                        lambda: _FakeService(items if items is not None
                                             else [_channel_item(EXPECTED_ID, EXPECTED_TITLE)]))
    calls = []
    monkeypatch.setattr(uy, "set_privacy",
                        lambda service, vid, privacy, publish_at=None:
                        calls.append((vid, privacy, publish_at)))
    monkeypatch.setattr("sys.argv", ["upload_youtube.py", "--publish-id", video_id])
    uy.main()
    return calls, json.loads(path.read_text(encoding="utf-8"))["videos"]


def test_publish_idで記録済みの動画を公開に戻せる(monkeypatch, tmp_path, capsys):
    calls, videos = _run_publish_id(
        monkeypatch, tmp_path, {"rec1": _entry("vid123")}, "vid123")

    assert calls == [("vid123", "public", None)]
    assert videos["rec1"]["privacy_status"] == "public"
    assert "公開しました" in capsys.readouterr().out


def test_publish_idは予約の記録も落とす(monkeypatch, tmp_path):
    """publish_at を残したままだと、予約が生きているように読める。
    即時公開したのだから、その枠の記録は持たない。
    """
    _, videos = _run_publish_id(
        monkeypatch, tmp_path,
        {"rec1": _entry("vid123", publish_at="2026-09-09T07:30:00+09:00")},
        "vid123")

    assert "publish_at" not in videos["rec1"]


def test_publish_idは記録に無い動画を触らない(monkeypatch, tmp_path, capsys):
    """記録に無い動画＝このパイプラインが作ったものではない。
    チャンネルには手作りの古い動画が150本以上あるので、取り違えると
    無関係な動画の公開設定を変えることになる。
    """
    with pytest.raises(SystemExit) as e:
        _run_publish_id(monkeypatch, tmp_path, {"rec1": _entry("vid123")}, "よその動画")

    assert e.value.code == 1
    assert "記録にありません" in capsys.readouterr().err


def test_publish_idは記録と別のチャンネルなら止まる(monkeypatch, tmp_path, capsys):
    """認証しているチャンネルと、記録に残っているチャンネルが違う状態。
    アップロード側と同じ終了コードで止める。
    """
    with pytest.raises(SystemExit) as e:
        _run_publish_id(monkeypatch, tmp_path,
                        {"rec1": _entry("vid123", channel_id="UCそのほか")}, "vid123")

    assert e.value.code == uy.EXIT_CHANNEL_MISMATCH
    assert "一致しません" in capsys.readouterr().err
