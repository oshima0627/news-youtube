#!/usr/bin/env python3
"""実写画像の取得。**取得元をホワイトリストで縛る。**

報道機関の写真には権利者のマークが入っている。それを消すのは著作権侵害を
隠す加工そのものなので、この実装は持たない。代わりに、
**元からマークの無い出所からしか取得しない**。

  首相官邸        PDL1.0            出典明示＋加工した旨と加工主体の記載
  各府省          政府標準利用規約2.0  出典明示
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
    """画像を落として license.json 用の記録を返す。"""
    if not is_allowed(url):
        raise ValueError(f"取得を許可していない出所です: {url}")
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return {"url": url, "attribution": attribution(url), "file": dest.name}
