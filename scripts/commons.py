#!/usr/bin/env python3
"""題材に合う実写画像を Wikimedia から自動で見つける。

**人物名の全文検索は使わない。** Commons を「片山さつき」で検索すると集合写真や
別人の写る画像が混ざるが、返ってきた画像に誰が写っているかを機械的に確かめる
手段が無い。代わりに **ja.wikipedia のその人物の記事に載っている画像**（記事の
代表画像）を引く。記事と人物は1対1なので、写っている人物が確定する。

ライセンスと解像度は Commons の imageinfo で改めて検証する。画像そのものの
取得は photos.download() が担い、そこでホスト（upload.wikimedia.org）の
ホワイトリスト検証がもう一度かかる。
"""

from __future__ import annotations

import re

import requests

from scripts.cards import PHOTO_H, SHORT_SIZE

WIKIPEDIA_API = "https://ja.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
TIMEOUT = 25

# Wikimedia は API 利用者に連絡先つきの User-Agent を求めている。
# 既定の python-requests のままだと弾かれることがある。
# <https://meta.wikimedia.org/wiki/User-Agent_policy>
USER_AGENT = "news-youtube/1.0 (https://github.com/oshima0627/news-youtube)"

# 動画に使ってよいライセンス。**これに一致するものだけを通す許可リスト**で、
# 拒否リストは持たない。「NC や ND を弾く」書き方を足すと、知らない表記が
# 出てきたときに素通りする。判断できないものは使わない、が正しい向き。
#
# 継承（SA）までは可、非営利限定（NC）と改変禁止（ND）は不可。動画には広告が
# 付き、画像は切り取って合成するので、どちらも条件を満たせない。NC・ND が
# 落ちるのは "cc-by-" の直後に数字を求めているため（"cc-by-nc-4.0" は
# "cc-by-n" で外れる）。
_ALLOWED_LICENSE_RE = re.compile(
    r"^(?:cc0(?:-1\.0)?|cc-by-\d|cc-by-sa-\d|pd(?:-.*)?|public\s*domain)", re.I)
# License コードが空の古い記述（"Attribution" など）向けの予備判定。
# こちらも許可リストで、末尾を固定して部分一致で緩まないようにしてある。
_ALLOWED_NAME_RE = re.compile(
    r"^(?:cc0|cc by(?:-sa)?\s|public domain|attribution$)", re.I)

# 写真は build_short._fill が写真枠（1080x659）を覆うまで拡大してから中央を
# 切り取る。したがって使えるかどうかを決めるのは画素数そのものではなく
# **拡大率**で、縦長のポートレートでは横幅が、横長の写真では高さが効く。
# 上限を超える画像は拡大の粗が出るので使わない。
#
# 固定の最小幅で判定すると、522x700 の公式ポートレート（拡大2.1倍、実用上
# 問題ない）を落として汎用画像に落ちる一方、大きくても極端に縦長な画像は
# 通ってしまう。実測では、この判定にしたことで玉木雄一郎の公式ポートレートが
# 本人の写真として使えるようになった。
PHOTO_TARGET = (SHORT_SIZE[0], PHOTO_H)
MAX_UPSCALE = 2.2

# 発言者の画像が取れなかったときに使う。国会での発言を扱う番組なので、
# 題材が何であっても文脈から外れない。ja.wikipedia の記事名で指定する
# （URLを直書きすると、その1枚が削除されたときに毎日失敗する）。
FALLBACK_ARTICLE = "国会議事堂"

# サムネイルの要求幅。原寸が小さければ Commons は原寸URLを返す。
THUMB_WIDTH = 1080


def _get(api: str, params: dict) -> dict:
    r = requests.get(api, timeout=TIMEOUT,
                     headers={"User-Agent": USER_AGENT},
                     params={"format": "json", "formatversion": "2", **params})
    r.raise_for_status()
    return r.json()


def lead_image_file(article: str) -> str | None:
    """ja.wikipedia の記事の代表画像のファイル名。無ければ None。

    `pilicense=free` を付けているので、非フリー画像（ロゴ等）は返ってこない。
    リダイレクト（「高市総理」→「高市早苗」など）は API 側で解決させる。
    """
    data = _get(WIKIPEDIA_API, {
        "action": "query", "titles": article, "redirects": "1",
        "prop": "pageimages", "piprop": "name", "pilicense": "free",
    })
    pages = data.get("query", {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return None
    return pages[0].get("pageimage")


def is_free(info: dict) -> bool:
    """動画に使えるライセンスか。判断できないものは通さない。"""
    code = (info.get("license") or "").strip()
    name = (info.get("license_name") or "").strip()
    return bool(_ALLOWED_LICENSE_RE.match(code) or _ALLOWED_NAME_RE.match(name))


def image_info(filename: str, width: int = THUMB_WIDTH) -> dict | None:
    """Commons からライセンス・寸法・取得URLを引く。"""
    data = _get(COMMONS_API, {
        "action": "query", "titles": f"File:{filename}",
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": width,
    })
    pages = data.get("query", {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return None
    infos = pages[0].get("imageinfo") or []
    if not infos:
        return None
    ii = infos[0]
    meta = ii.get("extmetadata") or {}

    def field(key: str) -> str:
        return str((meta.get(key) or {}).get("value", "")).strip()

    return {
        "file": filename,
        # 縮小版があればそちら。原寸が要求幅より小さければ Commons が原寸URLを返す
        "url": ii.get("thumburl") or ii.get("url") or "",
        "width": ii.get("width") or 0,
        "height": ii.get("height") or 0,
        "mime": ii.get("mime") or "",
        "license": field("License"),
        "license_name": field("LicenseShortName"),
        "artist": _strip_html(field("Artist")),
        "credit": _strip_html(field("Credit")),
        "descriptionurl": ii.get("descriptionurl") or "",
    }


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _strip_html(value: str) -> str:
    """extmetadata の Artist / Credit は HTML 断片で返る。表示用に均す。"""
    text = _TAG_RE.sub("", value)
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"')
                .replace("&#039;", "'").replace("&nbsp;", " "))
    return _SPACE_RE.sub(" ", text).strip()


def upscale(width: int, height: int) -> float:
    """写真枠を覆うために必要な拡大率。build_short._fill と同じ計算。"""
    if width <= 0 or height <= 0:
        return float("inf")
    tw, th = PHOTO_TARGET
    return max(tw / width, th / height)


def is_usable(info: dict | None) -> bool:
    """ライセンス・大きさ・形式のすべてが条件を満たすか。"""
    if not info or not info.get("url"):
        return False
    if not str(info.get("mime", "")).startswith("image/"):
        return False
    if upscale(info.get("width", 0), info.get("height", 0)) > MAX_UPSCALE:
        return False
    return is_free(info)


def find_image(article: str) -> dict | None:
    """記事名から、使える画像の情報を1件返す。無ければ None。"""
    if not article.strip():
        return None
    filename = lead_image_file(article)
    if not filename:
        return None
    info = image_info(filename)
    return info if is_usable(info) else None


def resolve(speaker: str) -> dict | None:
    """発言者の画像を探し、無ければ汎用画像に落とす。両方だめなら None。

    汎用画像（国会議事堂）は題材が何であっても文脈から外れないので、
    「画像が無いから題材を捨てる」ことがほぼ起きなくなる。
    """
    for article in (speaker, FALLBACK_ARTICLE):
        if not (article or "").strip():
            continue
        try:
            info = find_image(article)
        except Exception as e:            # noqa: BLE001 — 片方が落ちても次を試す
            print(f"! 画像の検索に失敗しました（{article}）: {e}")
            continue
        if info:
            info["article"] = article
            info["is_fallback"] = article != speaker
            return info
    return None


def credit(info: dict) -> str:
    """CC の表示義務を満たす出典表記を作る。

    作者・ライセンス名・出所ページの3つを出す。作者が取れないときは
    Wikimedia Commons を出所として示す。
    """
    who = info.get("artist") or info.get("credit") or "Wikimedia Commons"
    license_name = info.get("license_name") or info.get("license") or "Wikimedia Commons"
    where = info.get("descriptionurl") or info.get("url", "")
    return f"画像: {who} / {license_name}（{where}）"
