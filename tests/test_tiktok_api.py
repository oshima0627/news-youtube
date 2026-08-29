"""TikTok API クライアントのうち、HTTP を伴わない判断のテスト。

通信そのものはモックしても意味が薄いので、**送る前に決める値**と
**返ってきた状態の読み方**だけを縛る。ここを外すと init は通って
後段で失敗し、原因がログから読めなくなる。
"""

from __future__ import annotations

import json

import pytest

from scripts import tiktok
from scripts import tiktok_api as api


# ── 認証情報の不在 ─────────────────────────────────────────────

def test_client_jsonが無ければ何を用意すべきか出して止まる(tmp_path):
    with pytest.raises(api.TikTokAuthError) as e:
        api.TikTokApi.from_files(tmp_path)
    assert "tiktok_client.json" in str(e.value)


def test_token_jsonが無ければ認証コマンドを案内して止まる(tmp_path):
    (tmp_path / "tiktok_client.json").write_text(
        json.dumps({"client_key": "k", "client_secret": "s"}), encoding="utf-8")
    with pytest.raises(api.TikTokAuthError) as e:
        api.TikTokApi.from_files(tmp_path)
    assert "--auth-only" in str(e.value)


# ── アップロードのチャンク指定 ─────────────────────────────────

def test_小さい動画は1チャンクで送る():
    p = api.upload_params(3_898_089)
    assert p == {"video_size": 3_898_089, "chunk_size": 3_898_089,
                 "total_chunk_count": 1}


def test_上限ちょうどまでは1チャンクで送る():
    p = api.upload_params(api.MAX_CHUNK_BYTES)
    assert p["total_chunk_count"] == 1


def test_上限を超える動画は原因を出して止める():
    with pytest.raises(tiktok.TikTokError) as e:
        api.upload_params(api.MAX_CHUNK_BYTES + 1)
    assert "64" in str(e.value)


# ── 投稿完了の確認 ─────────────────────────────────────────────

def _fetcher(*statuses):
    seq = iter(statuses)

    def fetch(publish_id):
        return {"status": next(seq)}
    return fetch


def test_完了するまで待って結果を返す():
    result = api.await_complete("p1", fetch=_fetcher(
        "PROCESSING_UPLOAD", "PROCESSING_UPLOAD", "PUBLISH_COMPLETE"),
        sleep=lambda s: None)
    assert result["status"] == "PUBLISH_COMPLETE"


def test_失敗が返ったら待たずに例外にする():
    with pytest.raises(tiktok.TikTokError) as e:
        api.await_complete("p1", fetch=_fetcher("FAILED"), sleep=lambda s: None)
    assert "FAILED" in str(e.value)


def test_失敗が返ったときのメッセージに理由が入る():
    def fetch(publish_id):
        return {"status": "FAILED", "fail_reason": "video_format_check_failed"}

    with pytest.raises(tiktok.TikTokError) as e:
        api.await_complete("p1", fetch=fetch, sleep=lambda s: None)
    assert "video_format_check_failed" in str(e.value)


def test_いつまでも完了しなければ成功と書かずに止める():
    def fetch(publish_id):
        return {"status": "PROCESSING_UPLOAD"}

    with pytest.raises(tiktok.TikTokError) as e:
        api.await_complete("p1", fetch=fetch, sleep=lambda s: None,
                           max_attempts=3)
    assert "PROCESSING_UPLOAD" in str(e.value)


def test_完了を待つ回数は有限():
    calls = []

    def fetch(publish_id):
        calls.append(publish_id)
        return {"status": "PROCESSING_UPLOAD"}

    with pytest.raises(tiktok.TikTokError):
        api.await_complete("p1", fetch=fetch, sleep=lambda s: None,
                           max_attempts=4)
    assert len(calls) == 4


# ── トークンの期限 ─────────────────────────────────────────────

def test_期限が切れていればリフレッシュが要ると判定する():
    assert api.needs_refresh({"expires_at": 1000}, now=1001)


def test_期限が近いだけでもリフレッシュする():
    """投稿の途中で切れると、アップロード済みのまま publish に失敗する。"""
    assert api.needs_refresh({"expires_at": 1000}, now=1000 - api.REFRESH_MARGIN + 1)


def test_期限に余裕があればリフレッシュしない():
    assert not api.needs_refresh({"expires_at": 10_000}, now=1000)


def test_期限が記録されていなければリフレッシュする():
    assert api.needs_refresh({}, now=1000)


# ── PKCE ───────────────────────────────────────────────────────
#
# TikTok の code_challenge は **hex エンコードの SHA256**。一般的な PKCE
# 実装（base64url）をそのまま使うと認可サーバに拒否される。ここを外すと
# 認証が一切通らないので、実装を1箇所に閉じ込めて縛る。

def test_code_challengeはSHA256のhex():
    import hashlib

    verifier = "a" * 64
    expected = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    assert api.code_challenge(verifier) == expected


def test_code_challengeはbase64urlではない():
    challenge = api.code_challenge("a" * 64)
    assert len(challenge) == 64
    assert all(c in "0123456789abcdef" for c in challenge)


def test_code_verifierは仕様の長さに収まる():
    verifier = api.new_code_verifier()
    assert 43 <= len(verifier) <= 128


def test_code_verifierは未予約文字だけを使う():
    import string

    allowed = set(string.ascii_letters + string.digits + "-._~")
    assert set(api.new_code_verifier()) <= allowed


def test_code_verifierは毎回変わる():
    assert api.new_code_verifier() != api.new_code_verifier()


def test_認可URLに必要なパラメータが入る():
    url = api.authorize_url("my-key", "http://localhost:8723/callback",
                            code_challenge="abc123", state="st")
    assert url.startswith(api.AUTH_URL)
    for expected in ("client_key=my-key", "response_type=code",
                     "code_challenge=abc123", "code_challenge_method=S256",
                     "state=st"):
        assert expected in url
    assert "video.publish" in url


def test_トークン応答に期限の絶対時刻を足して保存する():
    token = api.token_from_response(
        {"access_token": "a", "refresh_token": "r", "open_id": "o",
         "expires_in": 86400}, now=1000)
    assert token["expires_at"] == 1000 + 86400
    assert token["open_id"] == "o"


def test_open_idが無い応答は認証エラーにする():
    """open_id が無いとアカウント取り違えガードが働かない。"""
    with pytest.raises(api.TikTokAuthError):
        api.token_from_response({"access_token": "a", "expires_in": 86400},
                                now=1000)
