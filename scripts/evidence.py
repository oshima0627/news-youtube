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
from dataclasses import asdict, dataclass, replace
from datetime import date
from urllib.parse import urlparse

import requests

from scripts.keywords import MIN_KEYWORDS

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
    # 発言者名。context にも入っているが、そちらは画面に出す表示用の文字列
    # なので、書式が変わると意味が変わる。画像の自動取得（commons.resolve）は
    # この名前で ja.wikipedia の記事を引くため、表示用の文字列を切り出すのでは
    # なく独立した項目として持つ。発言系以外の系統では空。
    speaker: str = ""


def _is_primary_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(EVIDENCE_HOST_SUFFIX)


def has_figure(figure: str) -> bool:
    """その文字列を数値カードに出してよいか（＝実際に数量を含むか）。

    採用ゲート（is_admissible）とカードの出し分け（build_short.compose_base /
    run_daily.ensure_grounded_card）で**同じ基準を使う**ための共有ヘルパ。

    もとは採用が `_FIGURE_RE.search()`、出し分けが `figure.strip()` と
    2種類あった。すると `figure="2024年度"` のような非数量文字列のとき、
    採用は quote 側の根拠で通るのに、カードは数値側に落ちる。数値カードに
    出るのはモデルが作った `figure_value` なので、**モデル生成値に一次資料の
    出典キャプションが付く**（引用カード側で塞いだのと同型の穴）。

    現状 `figure` は常に空なので到達しないが、e-Stat 統計系統を戻したときに
    効いてくる。戻すときに気づける保証が無いので先に揃えてある。
    """
    return bool(_FIGURE_RE.search(figure or ""))


# 引用カードに出す一節の長さ。逐語引用から機械的に抜き出すときの上限。
QUOTE_EXCERPT_MAX_CHARS = 25


def ground_excerpt(excerpt: str, quote: str) -> str:
    """引用カードに出してよい文字列を返す。**一次資料に由来することを保証する。**

    引用カードには必ず一次資料の出典キャプション（会議名・日付・発言者）が
    印字される。したがってカードに出す文字列が一次資料に無い言葉だと、
    **モデルが作った文字列に一次資料の出典が付く**ことになり、
    「一次資料が取れなければ公開しない」という設計方針がそこだけ破れる。

    `excerpt`（モデルが返した一節）が `quote`（逐語引用）の部分文字列なら
    そのまま返す。外れていたらモデルの出力を捨て、逐語引用の先頭から
    機械的に抜き出した文字列を返す。`quote` が空なら差し替えようが無いので
    空文字を返す（一次資料に無い文字列をそのまま通すことだけは避ける）。
    """
    quote = (quote or "").strip()
    excerpt = (excerpt or "").strip()
    if excerpt and excerpt in quote:
        return excerpt
    return quote[:QUOTE_EXCERPT_MAX_CHARS]


def is_admissible(ev: Evidence) -> bool:
    """出典URLと、具体的な数値または逐語引用の両方が揃っていれば True。"""
    if not ev.source_url or not _is_primary_host(ev.source_url):
        return False
    has_quote = len(ev.quote.strip()) >= MIN_QUOTE_CHARS
    return has_quote or has_figure(ev.figure)


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
                            context=context,
                            speaker=speaker))
    return out


SPEECH_LIMIT = 20

# 何年前までの発言を根拠として認めるか。国会会議録は1947年から入っている
# ので、指定しないと今日のニュースの根拠に10年前の答弁が返ってくる。
# 会議名と日付は画面にも概要欄にも出るので古いこと自体は隠れないが、
# 「今の政策の解説」として成立しなくなる。
SPEECH_SINCE_YEARS = 3


def since_date(today: date | None = None) -> str:
    """検索対象にする最古の発言日（YYYY-MM-DD）。"""
    d = today or date.today()
    return d.replace(year=d.year - SPEECH_SINCE_YEARS).isoformat()


def search_speeches(keyword: str, limit: int = SPEECH_LIMIT,
                    since: str | None = None) -> list[Evidence]:
    """国会会議録を全文検索する。認証キーは不要。

    `keyword` は空白区切り。API の `any` は空白区切りのAND検索なので、
    語を増やすほど絞られる（見出しをそのまま渡すと1件も当たらない）。

    一過性の失敗（5xx・タイムアウト等）は RETRY_ATTEMPTS 回まで指数バックオフ
    で粘り、それでも駄目なときだけ最後の例外を送出する。
    """
    last: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            r = requests.get(KOKKAI_ENDPOINT, timeout=TIMEOUT, params={
                "any": keyword,
                "from": since or since_date(),
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


# --- 関連性の判定 --------------------------------------------------------
#
# 国会の発言は1件2,000〜3,000字あるので、「検索語がその発言のどこかに
# 出てくる」を関連性の判定にすると何も判定できない。実測でも、その条件では
# 12件中12件が「関連あり」になった一方、中身は消費税減税の見出しに対して
# 憲法審査会の答弁、年金の見出しに対して NISA の答弁だった。
#
# そこで **異なる検索語が同じ文脈に固まって現れる箇所** を探し、そこだけを
# 引用として切り出す。見つからなければその発言は根拠にしない。
# これで「語がたまたま別々の話題に散らばっている発言」が落ちる。

PASSAGE_WINDOW = 220      # 「同じ文脈」とみなす幅
PASSAGE_LEAD = 60         # 最初の語より前を何字含めるか（文頭を拾うため）
PASSAGE_TAIL = 100        # 最後の語より後ろを何字含めるか（文末を拾うため）
PASSAGE_MIN_CHARS = 30    # 短すぎる断片は引用として使わない
MIN_DISTINCT_KEYWORDS = 2  # 窓の中に必要な「異なる検索語」の数

# 数値を含む箇所を優先するための目印。is_admissible の _FIGURE_RE ほど
# 厳密でなくてよい（採否ではなく同点候補の順位付けにしか使わない）が、
# 国会答弁は漢数字なので算用数字だけを見ていると全部素通りする。
_PASSAGE_FIGURE_RE = re.compile(
    r"[0-9０-９一二三四五六七八九十百千万億兆]+\s*"
    r"(?:%|％|割|倍|兆円|億円|万円|円|人|件|年間|ポイント)")


def find_passage(quote: str, words: list[str]) -> tuple[str, int] | None:
    """検索語が近接して現れる箇所を切り出す。(引用, 得点) か None。

    得点は同じ題材の候補どうしを比べるためだけのもので、採否には使わない
    （採否は「切り出せたかどうか」そのもの）。異なる検索語が多く揃うほど、
    そして数値を含むほど高い。
    """
    hits: list[tuple[int, str]] = []
    for w in words:
        start = 0
        while (i := quote.find(w, start)) >= 0:
            hits.append((i, w))
            start = i + 1
    if not hits:
        return None
    hits.sort()

    best: tuple[str, int] | None = None
    for i, (pos, _) in enumerate(hits):
        # 自分より後ろにある語だけを見る（hits は位置順なので i 以降で足りる）
        inside = [(p, w) for p, w in hits[i:] if p < pos + PASSAGE_WINDOW]
        near = {w for _, w in inside}
        if len(near) < MIN_DISTINCT_KEYWORDS:
            continue

        # 窓の終わりは「最後の検索語 + PASSAGE_TAIL」で決める。固定で
        # pos + PASSAGE_WINDOW まで取ると、語が窓の手前に固まっている場合に
        # 無関係な後続文を100字以上引きずり込む。
        last = max(p for p, _ in inside)
        lo = max(0, pos - PASSAGE_LEAD)
        hi = min(len(quote), min(last + PASSAGE_TAIL, pos + PASSAGE_WINDOW))
        seg = quote[lo:hi]

        # 文の区切りに合わせる。検索語を含む文から始めて、検索語を含む文で
        # 終える（前後にある無関係な文は落とす）。
        #   - 頭は「最初の検索語より前にある**最後の**句点」の次から。
        #     最初の句点で切ると、窓に入っただけの無関係な前文が残る。
        #   - 尻は「最後の検索語より後ろにある**最初の**句点」まで。
        #     最後の句点まで取ると、無関係な後続文を引きずり込む。
        # 位置を見ずに切ると、検索語より後ろの句点で頭を切って引用が
        # 丸ごと消える（根拠そのものが落ちる）。
        first_rel, last_rel = pos - lo, last - lo
        trimmed = seg
        head = seg.rfind("。", 0, first_rel)
        if head >= 0:
            trimmed = trimmed[head + 1:]
            last_rel -= head + 1
        tail = trimmed.find("。", last_rel)
        if tail >= 0:
            trimmed = trimmed[:tail + 1]
        trimmed = trimmed.strip()
        # 文単位に詰めた結果が短くなりすぎたら、詰める前の窓を使う
        # （1文が短い答弁で引用が消えるのを避ける）。
        seg = trimmed if len(trimmed) >= PASSAGE_MIN_CHARS else seg.strip()
        if len(seg) < PASSAGE_MIN_CHARS:
            continue

        pts = len(near) * 10 + (4 if _PASSAGE_FIGURE_RE.search(seg) else 0)
        if best is None or pts > best[1]:
            best = (seg, pts)
    return best


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

    `keyword` は空白区切りの検索語（keywords.extract の出力を join したもの）。
    返す Evidence の `quote` は**発言全文ではなく、検索語が近接して現れる
    箇所だけ**を切り出したものになる（find_passage 参照）。切り出せない
    発言は題材と無関係とみなして落とす。関連性の高い順に並べて返す。

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
    words = keyword.split()
    if len(words) < MIN_KEYWORDS:
        # 語が足りないと find_passage の近接判定が成立せず、関連性を
        # 確かめられないまま「当たった」ことになる。取得しに行かない。
        print(f"- 検索語が {len(words)} 語しかないため一次資料に当てません"
              f"（{MIN_KEYWORDS}語以上必要）: {keyword!r}")
        return []

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

    scored: list[tuple[int, Evidence]] = []
    for ev in found:
        got = find_passage(ev.quote, words)
        if not got:
            continue
        passage, pts = got
        narrowed = replace(ev, quote=passage)
        if is_admissible(narrowed):
            scored.append((pts, narrowed))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ev for _, ev in scored]
