#!/usr/bin/env python3
"""一次資料の取得と採用ゲート。

このモジュールがパイプライン全体の関門になる。
**根拠が取れなければ動画を作らない**を採用条件そのものにすることで、
YouTube の量産型コンテンツ判定と、完全自動での事実誤認の両方を
同じ1箇所で塞いでいる。
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

import requests

# 一次資料として認めるホストのサフィックス。ここを広げると「解説」が「転載」に変わる
# 許可範囲: 日本政府機関（*.go.jp）のオフィシャルサイト
EVIDENCE_HOST_SUFFIX = ".go.jp"

MIN_QUOTE_CHARS = 12

# 「具体的な数値」の判定。数字が1文字でもあれば通す判定にしていると、
# 統計表ID（"0003412345"）やページ番号（"p2"）、調査年度のように
# **数量ではないが数字を含む文字列**が採用ゲートを通ってしまう
# （Task 4 で e-Stat 系統をまるごと外す原因になったのと同じ穴）。
# そこで「数字（桁区切り・小数点を含んでよい）＋数量の単位」という形を必ず求める。
#
# 単位には「年」「月」「日」を**入れない**。これらは数量ではなく時点を表すため、
# 統計表メタデータの調査年度（"2024年度"）がそのまま数値として通ってしまい、
# 上と同じ穴が開く。尺・期間として使いたい「時間」「分間」「秒」は量なので入れる。
_FIGURE_UNITS = (
    r"%|％|割|厘|倍|ポイント|pt|"
    r"人|名|世帯|円|銭|ドル|ユーロ|元|ウォン|"
    r"件|回|票|議席|席|個|本|台|隻|機|社|校|カ国|か国|箇国|箇所|カ所|か所|"
    r"時間|分間|秒|"
    r"万|億|兆|千|百|キロ|メートル|km|kg|トン|リットル|℃|度"
)
_FIGURE_RE = re.compile(
    rf"[0-9０-９][0-9０-９,，.．]*\s*(?:{_FIGURE_UNITS})")


@dataclass(frozen=True)
class Evidence:
    kind: str          # "speech" | "statistics" | "release"
    source_url: str    # 一次資料のURL
    figure: str        # 具体的な数値（無ければ空）
    quote: str         # 逐語引用（無ければ空）
    context: str       # 会議名・統計名・発表日など


def _is_primary_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(EVIDENCE_HOST_SUFFIX)


def is_admissible(ev: Evidence) -> bool:
    """出典URLと、具体的な数値または逐語引用の両方が揃っていれば True。"""
    if not ev.source_url or not _is_primary_host(ev.source_url):
        return False
    has_quote = len(ev.quote.strip()) >= MIN_QUOTE_CHARS
    has_figure = bool(_FIGURE_RE.search(ev.figure))
    return has_quote or has_figure


def build_recipe(candidate: dict, ev: Evidence) -> dict:
    """候補 + 根拠から recipes/<id>.json の中身を組み立てる。

    `recipes/<id>.json` は「これさえ残っていれば動画を作り直せる」再現の単位
    なので、書き出す側が2箇所（run_daily.py と verify_source.py）に分かれて
    いると片方だけ形が変わったときに再現できないレシピが混ざる。
    組み立てはここ1箇所に置き、両方から呼ぶ。
    """
    return {
        "id": candidate["id"],
        "headline": candidate["title"],
        "keyword": candidate["keyword"],
        "category": candidate["category"],
        "evidence": asdict(ev),
    }


KOKKAI_ENDPOINT = "https://kokkai.ndl.go.jp/api/speech"
TIMEOUT = 20

# 一過性の失敗（5xx・タイムアウト）で日全体を落とさないためのリトライ。
# 系統が国会会議録の1つしか無い今、search_speeches が1回落ちることは
# collect() から見れば「全系統ダウン」と同じ意味になり、run_daily.py 側の
# 中止判断まで一直線につながる。候補20件を逐次叩く以上、5xx が1回混ざる
# 確率は無視できないので、送出する前にここで数回粘る。
RETRY_ATTEMPTS = 3          # 初回 + リトライ2回
RETRY_BACKOFF_SECONDS = 1.0  # 1秒 → 2秒 の指数バックオフ


def parse_speeches(payload: dict) -> list[Evidence]:
    """国会会議録APIの応答を Evidence に変換する。

    「次に。」のような進行発言が大量に混ざるので、
    根拠になる長さの無いものはここで落とす。
    """
    out: list[Evidence] = []
    records = payload.get("speechRecord") or []
    if isinstance(records, dict):
        # 繰り返し要素が1件のとき、配列ではなくオブジェクト単体で返ってくる実装があるためのガード
        records = [records]
    for rec in records:
        quote = (rec.get("speech") or "").strip()
        if len(quote) < MIN_QUOTE_CHARS:
            continue
        session = rec.get("session")
        house = rec.get("nameOfHouse") or ""
        meeting = rec.get("nameOfMeeting") or ""
        date = rec.get("date") or ""
        speaker = rec.get("speaker") or ""
        parts = [
            f"第{session}回国会" if session else "",
            f"{house}{meeting}",
            date,
            speaker,
        ]
        context = " ".join(p for p in parts if p)
        out.append(Evidence(kind="speech",
                            source_url=rec.get("speechURL") or "",
                            figure="",
                            quote=quote,
                            context=context))
    return out


def search_speeches(keyword: str, limit: int = 10) -> list[Evidence]:
    """国会会議録を全文検索する。認証キーは不要。

    一過性の失敗（5xx・タイムアウト等）は RETRY_ATTEMPTS 回まで指数バックオフ
    で粘り、それでも駄目なときだけ最後の例外を送出する。
    """
    last: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            r = requests.get(KOKKAI_ENDPOINT, timeout=TIMEOUT, params={
                "any": keyword,
                "recordPacking": "json",
                "maximumRecords": min(limit, 100),
            })
            r.raise_for_status()
            return parse_speeches(r.json())
        except Exception as e:            # noqa: BLE001 — 通信・パースの一過性失敗を再試行する
            last = e
            if attempt == RETRY_ATTEMPTS - 1:
                break
            wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
            print(f"! 国会会議録APIの取得に失敗しました（{wait:.0f}秒後に再試行 "
                  f"{attempt + 2}/{RETRY_ATTEMPTS}）: {e}")
            time.sleep(wait)
    raise last                             # type: ignore[misc]


class EvidenceSourcesUnavailable(RuntimeError):
    """一次資料の取得元が1系統も応答しなかった（環境・ネットワーク不備）。

    「取得には成功したが採用条件を満たす根拠が無かった」（正常系、空リストを
    返す）場合と区別するための例外。区別しないと、国会会議録APIが疎通不能
    なだけの日でも collect() が空リストを返し続け、呼び出し側
    （run_daily.py）からは「見送り（根拠なし）」にしか見えない。その結果、
    全候補ぶん同じ失敗を繰り返した末に終了コード0で「本日 0/2 本」とだけ
    表示され、環境が壊れていることに気づけない — というのが run_daily.py
    側で最悪とされている失敗パターンなので、ここで区別できるようにする。
    """


def collect(keyword: str) -> list[Evidence]:
    """一次資料の各系統に当てて、採用条件を満たした根拠だけを返す。

    現状は国会会議録（search_speeches）の1系統のみ。
    e-Stat 系統は一旦外してある — search_statistics が figure に入れていたのは
    統計表のメタデータ（調査年度・統計表ID）であって実際の統計値ではなく、
    is_admissible の「figure に数字が1文字でもあれば通す」判定を statistics 系統
    だけ骨抜きにしていたため（統計表IDにたまたま数字が入っているだけで採用ゲートを
    通過してしまう）。getStatsData を叩いて実際の統計値を取れるようになったら、
    このタプルに search_statistics を戻す。

    系統ごとに例外を握りつぶす構造は、系統を後から追加・復活しやすくするために
    あえて維持してある。ただし**全系統が例外で落ちた**（＝1件も取得に成功して
    いない）場合だけは、「採用条件を満たすものが無かった」という正常系の空リスト
    と区別するために EvidenceSourcesUnavailable を送出する。1系統以上が
    成功していれば（採用ゲートを通らなかっただけでも）従来どおり空リストを返す。
    """
    found: list[Evidence] = []
    sources = (lambda: search_speeches(keyword),)
    failures: list[str] = []
    for fetch in sources:
        try:
            found.extend(fetch())
        except Exception as e:            # noqa: BLE001 — 系統ごとに握りつぶす
            print(f"! 一次資料の取得に失敗しました（この系統は飛ばします）: {e}")
            failures.append(str(e))

    if len(failures) == len(sources):
        raise EvidenceSourcesUnavailable(
            f"一次資料の取得元が1系統も応答しませんでした（キーワード: {keyword}）: "
            + "; ".join(failures))

    return [ev for ev in found if is_admissible(ev)]
