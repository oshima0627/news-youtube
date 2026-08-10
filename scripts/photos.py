#!/usr/bin/env python3
"""実写画像の取得。**取得元をホワイトリストで縛る。**

報道機関の写真には権利者のマークが入っている。それを消すのは著作権侵害を
隠す加工そのものなので、この実装は持たない。代わりに、
**元からマークの無い出所からしか取得しない**。

  首相官邸        PDL1.0            出典明示＋加工した旨と加工主体の記載
  各府省          政府標準利用規約2.0  出典明示＋加工した旨と加工主体の記載
  Wikimedia       CC BY / CC BY-SA / PD  クレジット必須

<https://www.kantei.go.jp/jp/terms.html>
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = ("upload.wikimedia.org",)
ALLOWED_SUFFIX = ".go.jp"
TIMEOUT = 30
EDITOR = "news-youtube"
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB


def _host(url: str) -> str:
    p = urlparse(url)
    if p.scheme != "https":
        return ""
    return (p.hostname or "").lower()


def is_allowed(url: str) -> bool:
    """https かつホスト名がホワイトリストに一致するときだけ True。

    ホスト名で判定する。URL文字列に対する部分一致だと
    `https://example.com/kantei.go.jp/...` を通してしまう。
    """
    host = _host(url)
    return bool(host) and (host in ALLOWED_HOSTS or host.endswith(ALLOWED_SUFFIX))


def attribution(url: str) -> str:
    """説明欄に入れる出典表記を返す。"""
    host = _host(url)
    if host.endswith("kantei.go.jp"):
        return (f"出典: 首相官邸ホームページ（{url}）\n"
                f"※本コンテンツは上記を{EDITOR}が加工して作成しています。")
    if host == "upload.wikimedia.org":
        return f"画像: Wikimedia Commons（{url}）"
    return (f"出典: {host}（{url}）\n"
            f"※本コンテンツは上記を{EDITOR}が加工して作成しています。")


def download(url: str, dest: Path) -> dict:
    """画像を落として license.json 用の記録を返す。

    最終URLのホワイトリスト検証とサイズ・Content-Type チェックを行う。
    リダイレクト迂回を防ぐため、requests の追従リダイレクト後の最終URL
    に対しても is_allowed() で検証する。
    """
    if not is_allowed(url):
        raise ValueError(f"取得を許可していない出所です: {url}")

    # stream=True でレスポンスを受けながら、サイズ上限とContent-Type チェック
    r = requests.get(url, timeout=TIMEOUT, stream=True)
    r.raise_for_status()

    # リダイレクト後の最終URLも検証（リダイレクト迂回対策）
    if r.url != url and not is_allowed(r.url):
        raise ValueError(f"リダイレクト先が許可されていません: {r.url}")

    # Content-Type 検証
    content_type = r.headers.get("content-type", "").lower()
    if not content_type.startswith("image/"):
        raise ValueError(f"画像ではありません (Content-Type: {content_type})")

    # サイズ上限チェック
    content_length = r.headers.get("content-length")
    if content_length:
        size = int(content_length)
        if size > MAX_IMAGE_SIZE:
            raise ValueError(f"ファイルが大きすぎます: {size} > {MAX_IMAGE_SIZE}")

    # ストリームで受けながらサイズをチェック
    chunks = []
    total_size = 0
    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            chunks.append(chunk)
            total_size += len(chunk)
            if total_size > MAX_IMAGE_SIZE:
                raise ValueError(f"ファイルが大きすぎます: {total_size} > {MAX_IMAGE_SIZE}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"".join(chunks))
    return {"url": url, "attribution": attribution(url), "file": dest.name}
