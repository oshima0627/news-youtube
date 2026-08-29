#!/usr/bin/env python3
"""TikTok Content Posting API のクライアント。

  認証情報   tiktok_client.json   client_key と client_secret
  トークン   tiktok_token.json    アクセストークン24時間 / リフレッシュ365日

投稿を止める判断はここには置かない（`tiktok.py` にある）。ここは
「送る前に決める値」と「返ってきた状態の読み方」だけを持つ。
"""

from __future__ import annotations

import hashlib
import http.server
import json
import secrets
import string
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

from scripts import tiktok

API = "https://open.tiktokapis.com/v2"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = f"{API}/oauth/token/"

# 投稿に要るスコープ。creator_info/query も video.publish の配下にある。
SCOPES = "user.info.basic,video.publish"

# 1リクエストで送れるチャンクの上限。これを超える動画は分割送信が要るが、
# このパイプラインのショートは実測 3.9MB 以下（70〜80秒版でも十数MB）なので
# 分割は実装しない。将来超えたときに黙って壊れないよう、上限で止める。
MAX_CHUNK_BYTES = 64 * 1024 * 1024

# アクセストークンの期限がこの秒数以内なら先にリフレッシュする。
# 投稿の途中で切れると、動画のアップロードだけ済んで publish に失敗し、
# 「送ったのに出ていない」状態の切り分けが難しくなる。
REFRESH_MARGIN = 300

# 投稿完了の確認。Direct Post は非同期で、init が 200 でも後段で失敗しうる。
POLL_INTERVAL = 3
POLL_MAX_ATTEMPTS = 40      # 3秒 × 40 = 最大2分


class TikTokAuthError(RuntimeError):
    """認証情報が無い・使えない。"""


# code_verifier に使える文字（RFC 7636 の unreserved）。
_VERIFIER_ALPHABET = string.ascii_letters + string.digits + "-._~"


def new_code_verifier(length: int = 64) -> str:
    """PKCE の code_verifier を作る。43〜128文字の高エントロピー文字列。"""
    return "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(length))


def code_challenge(verifier: str) -> str:
    """code_verifier から code_challenge を作る。

    **TikTok は hex エンコードの SHA256 を要求する。** RFC 7636 の標準
    （base64url、パディング無し）ではない。一般的な PKCE ライブラリを
    そのまま使うと認可サーバに拒否され、しかも返るのは汎用の
    invalid_request なので原因に辿り着きにくい。ここを1箇所に閉じ込めておく。
    """
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


def authorize_url(client_key: str, redirect_uri: str, *,
                  code_challenge: str, state: str) -> str:
    """同意画面のURLを組む。"""
    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def token_from_response(data: dict, now: float | None = None) -> dict:
    """トークン応答を保存する形にする。

    `expires_in`（相対秒）だけだと、保存したファイルを後で読んだときに
    期限が判らない。絶対時刻に直して持つ。

    `open_id` が無い応答は受け付けない。open_id が無いと
    `tiktok.assert_expected_account` が働かず、アカウント取り違えを
    投稿前に止められなくなる。
    """
    now = time.time() if now is None else now
    if not data.get("open_id"):
        raise TikTokAuthError(
            f"トークン応答に open_id がありません: {data}。"
            "open_id が無いとアカウント取り違えを防げないので受け付けません")
    token = dict(data)
    token["expires_at"] = now + data.get("expires_in", 0)
    return token


def authorize(root: Path, port: int = 8723) -> dict:
    """ブラウザで同意画面を開き、トークンを tiktok_token.json に保存する。

    TikTok は desktop app に PKCE を要求する。`code_challenge` が
    hex エンコードの SHA256 である点に注意（`code_challenge` 参照）。

    リダイレクトURI は TikTok アプリの設定に**同じ文字列で**登録して
    おく必要がある。食い違うと同意画面が redirect_uri のエラーで止まる。
    """
    root = Path(root)
    client_path = root / "tiktok_client.json"
    if not client_path.exists():
        raise TikTokAuthError(
            f"{client_path.name} がありません。"
            "TikTok for Developers で作った client_key / client_secret を"
            "JSON で置いてください")
    client = json.loads(client_path.read_text(encoding="utf-8"))

    redirect_uri = f"http://localhost:{port}/callback"
    verifier = new_code_verifier()
    state = secrets.token_urlsafe(16)
    received: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                       # noqa: N802
            query = urllib.parse.urlparse(self.path).query
            received.update(urllib.parse.parse_qs(query))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h1>認証しました</h1><p>このタブは閉じてかまいません。</p>"
                .encode("utf-8"))

        def log_message(self, *args):           # サーバのアクセスログは出さない
            pass

    server = http.server.HTTPServer(("localhost", port), Handler)
    url = authorize_url(client["client_key"], redirect_uri,
                        code_challenge=code_challenge(verifier), state=state)
    print("- ブラウザで同意画面を開きます。開かない場合は"
          "このURLを開いてください:")
    print(f"  {url}")
    webbrowser.open(url)
    threading.Thread(target=server.handle_request, daemon=True).start()
    server.socket.settimeout(300)
    while not received:
        time.sleep(0.5)
    server.server_close()

    if received.get("state", [None])[0] != state:
        raise TikTokAuthError(
            "state が一致しません。認証をやり直してください")
    code = received.get("code", [None])[0]
    if not code:
        raise TikTokAuthError(f"認可コードを受け取れませんでした: {received}")

    r = requests.post(TOKEN_URL, data={
        "client_key": client["client_key"],
        "client_secret": client["client_secret"],
        "code": urllib.parse.unquote(code),
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30)
    if r.status_code != 200:
        raise TikTokAuthError(
            f"トークンを取得できませんでした（HTTP {r.status_code}）: {r.text}")

    token = token_from_response(r.json())
    (root / "tiktok_token.json").write_text(
        json.dumps(token, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("✓ tiktok_token.json を保存しました（コミットしないこと）")
    return token


def upload_params(video_size: int) -> dict:
    """FILE_UPLOAD の source_info に入れるサイズ指定。

    分割は実装しない（このパイプラインの動画は十数MBに収まる）。上限を
    超えたら黙って壊れず、原因を出して止める。
    """
    if video_size > MAX_CHUNK_BYTES:
        raise tiktok.TikTokError(
            f"動画が{video_size / 1024 / 1024:.1f}MBあり、1回で送れる上限"
            f"（64MB）を超えています。分割送信は実装していません")
    return {"video_size": video_size, "chunk_size": video_size,
            "total_chunk_count": 1}


def needs_refresh(token: dict, now: float | None = None) -> bool:
    """アクセストークンを先にリフレッシュすべきか。

    期限が記録されていない場合も True。記録が無いまま使って 401 で落ちるより、
    1回リフレッシュするほうが安い。
    """
    now = time.time() if now is None else now
    expires_at = token.get("expires_at")
    if expires_at is None:
        return True
    return now >= expires_at - REFRESH_MARGIN


def await_complete(publish_id: str, *, fetch, sleep=time.sleep,
                   interval: float = POLL_INTERVAL,
                   max_attempts: int = POLL_MAX_ATTEMPTS) -> dict:
    """投稿が完了するまで待つ。完了を確認できなければ例外にする。

    **init の 200 だけで成功と書かない。** 記録してしまうと、失敗した投稿が
    「投稿済み」になってキューから外れ、二度と出せなくなる。
    """
    status = None
    for attempt in range(max_attempts):
        result = fetch(publish_id)
        status = result.get("status")
        if status == "PUBLISH_COMPLETE":
            return result
        if status == "FAILED":
            reason = result.get("fail_reason") or "（理由の記載なし）"
            raise tiktok.TikTokError(
                f"投稿が失敗しました（status=FAILED, publish_id={publish_id}）: "
                f"{reason}")
        if attempt < max_attempts - 1:
            sleep(interval)
    raise tiktok.TikTokError(
        f"投稿の完了を確認できませんでした（最後の status={status}, "
        f"publish_id={publish_id}）。TikTok アプリで下書き・投稿の有無を"
        "確かめてください。投稿済みとしては記録していません")


class TikTokApi:
    """アクセストークンを持ち、投稿に必要な呼び出しだけを提供する。"""

    def __init__(self, root: Path, client: dict, token: dict):
        self.root = Path(root)
        self.client = client
        self.token = token

    # ── 生成 ──────────────────────────────────────────────────
    @classmethod
    def from_files(cls, root: Path) -> "TikTokApi":
        root = Path(root)
        client_path = root / "tiktok_client.json"
        token_path = root / "tiktok_token.json"
        if not client_path.exists():
            raise TikTokAuthError(
                f"{client_path.name} がありません。\n"
                "  TikTok for Developers でアプリを作り、Content Posting API を\n"
                "  追加して Direct Post を有効化したうえで、client_key と\n"
                "  client_secret を JSON で置いてください\n"
                "  （このファイルはコミットしないこと）")
        client = json.loads(client_path.read_text(encoding="utf-8"))
        if not token_path.exists():
            raise TikTokAuthError(
                f"{token_path.name} がありません。\n"
                "  python scripts/upload_tiktok.py --auth-only を実行して、\n"
                "  ブラウザで認証してください")
        token = json.loads(token_path.read_text(encoding="utf-8"))
        api = cls(root, client, token)
        api._ensure_token()
        return api

    # ── トークン ──────────────────────────────────────────────
    def _save_token(self) -> None:
        (self.root / "tiktok_token.json").write_text(
            json.dumps(self.token, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    def _ensure_token(self) -> None:
        if not needs_refresh(self.token):
            return
        refresh = self.token.get("refresh_token")
        if not refresh:
            raise TikTokAuthError(
                "リフレッシュトークンがありません。"
                "python scripts/upload_tiktok.py --auth-only で認証し直してください")
        r = requests.post(TOKEN_URL, data={
            "client_key": self.client["client_key"],
            "client_secret": self.client["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30)
        if r.status_code != 200:
            raise TikTokAuthError(
                f"トークンを更新できませんでした（HTTP {r.status_code}）: {r.text}\n"
                "  リフレッシュトークンは365日で失効します。"
                "--auth-only で認証し直してください")
        data = r.json()
        self.token.update(data)
        self.token["expires_at"] = time.time() + data.get("expires_in", 0)
        self._save_token()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token['access_token']}",
                "Content-Type": "application/json; charset=UTF-8"}

    def open_id(self) -> str:
        return self.token["open_id"]

    # ── API ───────────────────────────────────────────────────
    def creator_info(self) -> dict:
        r = requests.post(f"{API}/post/publish/creator_info/query/",
                          headers=self._headers(), timeout=30)
        if r.status_code != 200:
            raise tiktok.TikTokError(
                f"creator_info を取得できませんでした（HTTP {r.status_code}）: "
                f"{r.text}")
        return r.json().get("data", {})

    def publish(self, *, video: Path, caption: str, privacy_level: str) -> str:
        """Direct Post を開始し、動画を送って publish_id を返す。"""
        video = Path(video)
        size = video.stat().st_size
        body = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_stitch": False,
                "disable_comment": False,
            },
            "source_info": {"source": "FILE_UPLOAD", **upload_params(size)},
        }
        r = requests.post(f"{API}/post/publish/video/init/",
                          headers=self._headers(), json=body, timeout=60)
        if r.status_code != 200:
            raise tiktok.TikTokError(
                f"投稿を開始できませんでした（HTTP {r.status_code}）: {r.text}")
        data = r.json().get("data", {})
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")
        if not publish_id or not upload_url:
            raise tiktok.TikTokError(
                f"init の応答に publish_id / upload_url がありません: {r.text}")

        put = requests.put(upload_url, data=video.read_bytes(), headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        }, timeout=300)
        if put.status_code not in (200, 201, 202):
            raise tiktok.TikTokError(
                f"動画を送れませんでした（HTTP {put.status_code}）: {put.text}")
        return publish_id

    def _fetch_status(self, publish_id: str) -> dict:
        r = requests.post(f"{API}/post/publish/status/fetch/",
                          headers=self._headers(),
                          json={"publish_id": publish_id}, timeout=30)
        if r.status_code != 200:
            raise tiktok.TikTokError(
                f"投稿の状態を取得できませんでした（HTTP {r.status_code}）: {r.text}")
        return r.json().get("data", {})

    def await_complete(self, publish_id: str) -> dict:
        return await_complete(publish_id, fetch=self._fetch_status)
