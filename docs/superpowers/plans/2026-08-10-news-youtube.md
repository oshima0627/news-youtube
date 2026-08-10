# news-youtube 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RSSで拾ったニュースを一次資料に当て、根拠が取れたものだけを1日2本のショート動画にして YouTube に自動投稿する。

**Architecture:** 毎朝1回 `run_daily.py` を起動し、候補収集 → 採用ゲート → 台本 → 画像 → 音声 → 合成 → private アップ → 予約公開 を通しで実行する。純粋な判定ロジック（スロット計算・採用ゲート・ホワイトリスト・スコアリング）を CLI から切り離したモジュールに置き、そこを手厚くテストする。副作用のある層（HTTP・ffmpeg・YouTube API）は薄く保つ。

**Tech Stack:** Python 3.13 / Pillow / requests / anthropic (`claude-opus-5`) / VOICEVOX ローカルエンジン / ffmpeg / google-api-python-client / pytest

## Global Constraints

- チャンネルID は `UCYHTfHJOoETzvpx-VZlUTng`。`meta.json` の `expected_channel_id` に必ず入れ、不一致ならアップロードしない。
- 動画は 1080×1920、尺は 56〜61秒に収める。
- ナレーションは VOICEVOX の **青山龍星**。話者IDはハードコードせず `/speakers` から名前で解決する。
- Claude API は `claude-opus-5`、adaptive thinking、構造化出力（`client.messages.parse()`）を使う。
- 画像の取得元は `kantei.go.jp` / `*.go.jp` / `upload.wikimedia.org` のみ。**それ以外のドメインからは取得しない。**
- 採用条件は「出典URL」と「具体的な数値または逐語引用」の**両方**。片方でも欠けたら不採用。
- 台本生成に RSS の本文を渡さない。渡すのは一次資料の抜粋のみ。
- 過去のスロットは遡って埋めない。18:30 を過ぎて起動した日はその日を捨てる。
- 認証情報（`client_secret.json` / `token.json` / `.env`）はコミットしない。

---

## ファイル構成

| ファイル | 責務 |
| --- | --- |
| `scripts/slots.py` | 起動時刻から当日の未経過スロットを計算する（純関数） |
| `scripts/evidence.py` | 一次資料の取得と採用ゲート判定 |
| `scripts/photos.py` | 取得元ホワイトリスト判定と画像ダウンロード |
| `scripts/sources.py` | RSS取得と題材スコアリング（純関数） |
| `scripts/script_writer.py` | Claude API で台本生成 |
| `scripts/draw.py` | フォント・折り返し・配色の共通部品 |
| `scripts/cards.py` | 縦型フレームと数値カードの描画 |
| `scripts/narrate.py` | VOICEVOX で音声合成 |
| `scripts/collect_news.py` | CLI: `sources` → `work/candidates.json` |
| `scripts/verify_source.py` | CLI: `evidence` → `recipes/<id>.json` |
| `scripts/fetch_photo.py` | CLI: `photos` → `work/<id>/photo.jpg` + `license.json` |
| `scripts/write_script.py` | CLI: `script_writer` → `work/<id>/script.json` |
| `scripts/build_short.py` | CLI: 画像＋音声＋フレーム → `work/<id>/video.mp4` |
| `scripts/upload_youtube.py` | CLI: private アップ / `--schedule` / `--publish` |
| `scripts/unpublish.py` | CLI: 公開後の緊急停止 |
| `scripts/run_daily.py` | 上記を順に回すオーケストレータ |

判定ロジック（`slots` / `evidence` / `photos` / `sources`）を CLI から分けているのは、
**壊れると事故がそのまま公開される箇所だけを純関数にしてテストで固めるため**。

---

### Task 1: 土台とスロット計算

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/slots.py`
- Create: `pytest.ini`
- Test: `tests/test_slots.py`

**Interfaces:**
- Consumes: なし
- Produces: `slots.PUBLISH_SLOTS: tuple[time, time]`、`slots.pending_slots(now: datetime) -> list[datetime]`

- [ ] **Step 1: pytest の設定と空パッケージを作る**

`pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

`scripts/__init__.py`: 空ファイル。

```bash
mkdir tests
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_slots.py`:

```python
from datetime import datetime

from scripts.slots import pending_slots


def test_早朝起動なら当日2枠とも返る():
    got = pending_slots(datetime(2026, 8, 11, 6, 0))
    assert got == [datetime(2026, 8, 11, 7, 30), datetime(2026, 8, 11, 18, 30)]


def test_昼に起動したら夕方の枠だけ返る():
    got = pending_slots(datetime(2026, 8, 11, 12, 0))
    assert got == [datetime(2026, 8, 11, 18, 30)]


def test_夕方の枠を過ぎたら空になる():
    # 過去分は遡って埋めない。古いニュースを今出しても伸びない
    assert pending_slots(datetime(2026, 8, 11, 19, 0)) == []


def test_枠の時刻ちょうどは過ぎたものとして扱う():
    # 予約公開は未来時刻でないと受け付けられない
    assert pending_slots(datetime(2026, 8, 11, 7, 30)) == [
        datetime(2026, 8, 11, 18, 30)
    ]
```

- [ ] **Step 3: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_slots.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.slots'`

- [ ] **Step 4: 最小の実装を書く**

`scripts/slots.py`:

```python
#!/usr/bin/env python3
"""投稿枠の計算。

1日2本を JST 07:30 と 18:30 に予約公開する。
起動時にまだ来ていない枠だけを返し、**過ぎた枠は遡って埋めない**。
古いニュースを後から出しても伸びず、量産型の印象を強めるだけなので。
"""

from __future__ import annotations

from datetime import datetime, time

PUBLISH_SLOTS = (time(7, 30), time(18, 30))


def pending_slots(now: datetime) -> list[datetime]:
    """now の時点でまだ来ていない当日の枠を、早い順に返す。"""
    return [
        datetime.combine(now.date(), t)
        for t in PUBLISH_SLOTS
        if datetime.combine(now.date(), t) > now
    ]
```

- [ ] **Step 5: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_slots.py -v`
Expected: PASS（4件）

- [ ] **Step 6: コミット**

```bash
git add pytest.ini scripts/__init__.py scripts/slots.py tests/test_slots.py
git commit -m "feat: 投稿枠の計算を追加（過去分は埋めない）"
```

---

### Task 2: 採用ゲートの判定

**Files:**
- Create: `scripts/evidence.py`
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: なし
- Produces: `evidence.Evidence` (dataclass: `kind: str`, `source_url: str`, `figure: str`, `quote: str`, `context: str`)、`evidence.is_admissible(ev: Evidence) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_evidence.py`:

```python
from scripts.evidence import Evidence, is_admissible


def _ev(**kw) -> Evidence:
    base = dict(kind="speech", source_url="https://kokkai.ndl.go.jp/#/detail?x=1",
                figure="", quote="議員定数を45削減すると申し上げた",
                context="第217回国会 予算委員会 2025-11-20")
    base.update(kw)
    return Evidence(**base)


def test_逐語引用と出典があれば採用する():
    assert is_admissible(_ev()) is True


def test_数値と出典があれば採用する():
    assert is_admissible(_ev(quote="", figure="関西空港便が30%減")) is True


def test_出典URLが無ければ不採用():
    assert is_admissible(_ev(source_url="")) is False


def test_数値も引用も無ければ不採用():
    assert is_admissible(_ev(quote="", figure="")) is False


def test_出典URLがホワイトリスト外なら不採用():
    # 一次資料以外を根拠にすると、その時点で「解説」ではなく「転載」になる
    assert is_admissible(_ev(source_url="https://example.com/news/1")) is False


def test_引用が短すぎるものは根拠として認めない():
    assert is_admissible(_ev(quote="そうだ")) is False


def test_数値らしい文字を含まない図表値は認めない():
    assert is_admissible(_ev(quote="", figure="大幅に増加した")) is False
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.evidence'`

- [ ] **Step 3: 最小の実装を書く**

`scripts/evidence.py`:

```python
#!/usr/bin/env python3
"""一次資料の取得と採用ゲート。

このモジュールがパイプライン全体の関門になる。
**根拠が取れなければ動画を作らない**を採用条件そのものにすることで、
YouTube の量産型コンテンツ判定と、完全自動での事実誤認の両方を
同じ1箇所で塞いでいる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# 一次資料として認めるホスト。ここを広げると「解説」が「転載」に変わる
EVIDENCE_HOSTS = ("kokkai.ndl.go.jp", "www.e-stat.go.jp", "e-stat.go.jp")
EVIDENCE_HOST_SUFFIX = ".go.jp"

MIN_QUOTE_CHARS = 12
_FIGURE_RE = re.compile(r"[0-9０-９]")


@dataclass(frozen=True)
class Evidence:
    kind: str          # "speech" | "statistics" | "release"
    source_url: str    # 一次資料のURL
    figure: str        # 具体的な数値（無ければ空）
    quote: str         # 逐語引用（無ければ空）
    context: str       # 会議名・統計名・発表日など


def _is_primary_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in EVIDENCE_HOSTS or host.endswith(EVIDENCE_HOST_SUFFIX)


def is_admissible(ev: Evidence) -> bool:
    """出典URLと、具体的な数値または逐語引用の両方が揃っていれば True。"""
    if not ev.source_url or not _is_primary_host(ev.source_url):
        return False
    has_quote = len(ev.quote.strip()) >= MIN_QUOTE_CHARS
    has_figure = bool(_FIGURE_RE.search(ev.figure))
    return has_quote or has_figure
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: PASS（7件）

- [ ] **Step 5: コミット**

```bash
git add scripts/evidence.py tests/test_evidence.py
git commit -m "feat: 採用ゲートの判定を追加（出典＋数値/引用の両方を必須にする）"
```

---

### Task 3: 国会会議録APIから過去発言を引く

**Files:**
- Modify: `scripts/evidence.py`
- Create: `tests/fixtures/kokkai_speech.json`
- Modify: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `evidence.Evidence`
- Produces: `evidence.parse_speeches(payload: dict) -> list[Evidence]`、`evidence.search_speeches(keyword: str, limit: int = 10) -> list[Evidence]`

- [ ] **Step 1: APIのレスポンスを固定データとして保存する**

`tests/fixtures/kokkai_speech.json`（国会会議録検索API `/api/speech` の応答を最小化したもの）:

```json
{
  "numberOfRecords": 2,
  "speechRecord": [
    {
      "speechID": "121705261X00120251120_001",
      "session": 217,
      "nameOfHouse": "衆議院",
      "nameOfMeeting": "予算委員会",
      "date": "2025-11-20",
      "speaker": "野田佳彦",
      "speakerGroup": "立憲民主党",
      "speech": "私どもは議員定数を四十五削減すると申し上げてまいりました。",
      "speechURL": "https://kokkai.ndl.go.jp/#/detail?minId=121705261X00120251120&spkNum=1"
    },
    {
      "speechID": "121705261X00120251120_002",
      "session": 217,
      "nameOfHouse": "衆議院",
      "nameOfMeeting": "予算委員会",
      "date": "2025-11-20",
      "speaker": "委員長",
      "speakerGroup": "",
      "speech": "次に。",
      "speechURL": "https://kokkai.ndl.go.jp/#/detail?minId=121705261X00120251120&spkNum=2"
    }
  ]
}
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_evidence.py` の末尾に追記:

```python
import json
from pathlib import Path

from scripts.evidence import parse_speeches

FIXTURES = Path(__file__).parent / "fixtures"


def test_発言をEvidenceに変換する():
    payload = json.loads((FIXTURES / "kokkai_speech.json").read_text(encoding="utf-8"))
    got = parse_speeches(payload)

    assert len(got) == 1                       # 短すぎる進行発言は落ちる
    ev = got[0]
    assert ev.kind == "speech"
    assert ev.quote == "私どもは議員定数を四十五削減すると申し上げてまいりました。"
    assert ev.source_url.startswith("https://kokkai.ndl.go.jp/")
    assert "予算委員会" in ev.context
    assert "野田佳彦" in ev.context
    assert is_admissible(ev) is True


def test_発言が空のレスポンスは空リストになる():
    assert parse_speeches({"numberOfRecords": 0}) == []
```

- [ ] **Step 3: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_speeches'`

- [ ] **Step 4: 実装を書く**

`scripts/evidence.py` の末尾に追記:

```python
import requests

KOKKAI_ENDPOINT = "https://kokkai.ndl.go.jp/api/speech"
TIMEOUT = 20


def parse_speeches(payload: dict) -> list[Evidence]:
    """国会会議録APIの応答を Evidence に変換する。

    「次に。」のような進行発言が大量に混ざるので、
    根拠になる長さの無いものはここで落とす。
    """
    out: list[Evidence] = []
    for rec in payload.get("speechRecord") or []:
        quote = (rec.get("speech") or "").strip()
        if len(quote) < MIN_QUOTE_CHARS:
            continue
        speaker = rec.get("speaker") or ""
        context = (f"第{rec.get('session')}回国会 {rec.get('nameOfHouse')}"
                   f"{rec.get('nameOfMeeting')} {rec.get('date')} {speaker}")
        out.append(Evidence(kind="speech",
                            source_url=rec.get("speechURL") or "",
                            figure="",
                            quote=quote,
                            context=context.strip()))
    return out


def search_speeches(keyword: str, limit: int = 10) -> list[Evidence]:
    """国会会議録を全文検索する。認証キーは不要。"""
    r = requests.get(KOKKAI_ENDPOINT, timeout=TIMEOUT, params={
        "any": keyword,
        "recordPacking": "json",
        "maximumRecords": min(limit, 100),
    })
    r.raise_for_status()
    return parse_speeches(r.json())
```

- [ ] **Step 5: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: PASS（9件）

- [ ] **Step 6: 実際のAPIに1回だけ当てて疎通を確かめる**

Run:

```bash
python -c "from scripts.evidence import search_speeches; e=search_speeches('議員定数', 3); print(len(e)); print(e[0].context if e else 'なし')"
```

Expected: 件数と会議名が表示される。0件やエラーなら `any` パラメータ名と `recordPacking=json` を API仕様（<https://kokkai.ndl.go.jp/api.html>）と突き合わせて直す。

- [ ] **Step 7: コミット**

```bash
git add scripts/evidence.py tests/test_evidence.py tests/fixtures/kokkai_speech.json
git commit -m "feat: 国会会議録APIから過去発言を引く"
```

---

### Task 4: e-Stat と報道発表を足して verify_source を作る

**Files:**
- Modify: `scripts/evidence.py`
- Create: `scripts/verify_source.py`
- Modify: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `evidence.Evidence`, `evidence.is_admissible`, `evidence.search_speeches`
- Produces: `evidence.search_statistics(keyword: str) -> list[Evidence]`、`evidence.collect(keyword: str) -> list[Evidence]`、`verify_source.build_recipe(candidate: dict, ev: Evidence) -> dict`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_evidence.py` の末尾に追記:

```python
from scripts.evidence import collect


def test_collectは落ちた系統を飛ばして残りを返す(monkeypatch):
    ok = Evidence(kind="speech", source_url="https://kokkai.ndl.go.jp/#/x",
                  figure="", quote="議員定数を四十五削減すると申し上げた",
                  context="予算委員会")

    def boom(_keyword):
        raise RuntimeError("e-Stat が落ちている")

    monkeypatch.setattr("scripts.evidence.search_speeches", lambda k, limit=10: [ok])
    monkeypatch.setattr("scripts.evidence.search_statistics", boom)

    assert collect("議員定数") == [ok]


def test_collectは全系統が落ちたら空になる(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("落ちている")

    monkeypatch.setattr("scripts.evidence.search_speeches", boom)
    monkeypatch.setattr("scripts.evidence.search_statistics", boom)

    assert collect("議員定数") == []
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: FAIL — `ImportError: cannot import name 'collect'`

- [ ] **Step 3: 実装を書く**

`scripts/evidence.py` の末尾に追記:

```python
import os

ESTAT_ENDPOINT = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList"


def search_statistics(keyword: str) -> list[Evidence]:
    """e-Stat の統計表を検索する。appId が無ければ何も返さない。

    統計表そのものは数値の塊なので、ここでは「どの統計に当たれば数字が
    あるか」までを Evidence にし、figure には統計表の件数を入れる。
    """
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        return []
    r = requests.get(ESTAT_ENDPOINT, timeout=TIMEOUT, params={
        "appId": app_id, "searchWord": keyword, "limit": 5,
    })
    r.raise_for_status()
    body = r.json().get("GET_STATS_LIST", {})
    if str(body.get("RESULT", {}).get("STATUS")) != "0":
        return []
    tables = body.get("DATALIST_INF", {}).get("TABLE_INF") or []
    if isinstance(tables, dict):
        tables = [tables]

    out: list[Evidence] = []
    for t in tables:
        stats_id = t.get("@id") or ""
        title = t.get("STATISTICS_NAME") or ""
        survey = t.get("SURVEY_DATE") or ""
        if not stats_id:
            continue
        out.append(Evidence(
            kind="statistics",
            source_url=f"https://www.e-stat.go.jp/dbview?sid={stats_id}",
            figure=f"{survey}" if survey else stats_id,
            quote="",
            context=f"e-Stat {title}".strip()))
    return out


def collect(keyword: str) -> list[Evidence]:
    """3系統に当てて、採用条件を満たした根拠だけを返す。

    落ちている系統はスキップし、残りで判定を続ける。
    全系統が失敗したら空を返す（＝その題材は作らない）。
    """
    found: list[Evidence] = []
    for fetch in (lambda: search_speeches(keyword),
                  lambda: search_statistics(keyword)):
        try:
            found.extend(fetch())
        except Exception as e:            # noqa: BLE001 — 系統ごとに握りつぶす
            print(f"! 一次資料の取得に失敗しました（この系統は飛ばします）: {e}")
    return [ev for ev in found if is_admissible(ev)]
```

> 報道発表（3系統目）は府省ごとにHTML構造が違い、汎用の実装が持てない。
> `search_speeches` と `search_statistics` の2系統で採用率を実測してから、
> 必要なら省庁を絞って足す。`collect` は関数を並べるだけなので後から追加できる。

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: PASS（11件）

- [ ] **Step 5: verify_source の CLI を書く**

`scripts/verify_source.py`:

```python
#!/usr/bin/env python3
"""候補を一次資料に当てて、通ったものだけ recipes/<id>.json にする。

  python scripts/verify_source.py --want 2

candidates.json を上から順に当て、--want 件そろった時点で打ち切る。
そろわなければ少ないまま返す。**無理に埋めない。**
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "work" / "candidates.json"
RECIPES = ROOT / "recipes"

from scripts.evidence import Evidence, collect  # noqa: E402


def build_recipe(candidate: dict, ev: Evidence) -> dict:
    return {
        "id": candidate["id"],
        "headline": candidate["title"],
        "keyword": candidate["keyword"],
        "category": candidate["category"],
        "evidence": asdict(ev),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--want", type=int, default=2)
    a = ap.parse_args()

    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    RECIPES.mkdir(parents=True, exist_ok=True)

    made: list[str] = []
    for c in candidates:
        if len(made) >= a.want:
            break
        found = collect(c["keyword"])
        if not found:
            print(f"- 見送り（根拠なし）: {c['title'][:32]}")
            continue
        recipe = build_recipe(c, found[0])
        path = RECIPES / f"{c['id']}.json"
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        made.append(c["id"])
        print(f"✓ 採用: {c['title'][:32]}  根拠={found[0].kind}")

    print(f"採用 {len(made)}/{a.want} 件")
    if len(made) < a.want:
        print("! 根拠の取れた題材が足りません。本数を減らして続行します")
    print(json.dumps(made, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: コミット**

```bash
git add scripts/evidence.py scripts/verify_source.py tests/test_evidence.py
git commit -m "feat: e-Stat を足して採用ゲートのCLIを作る"
```

---

### Task 5: 画像の取得元ホワイトリスト

**Files:**
- Create: `scripts/photos.py`
- Create: `scripts/fetch_photo.py`
- Test: `tests/test_photos.py`

**Interfaces:**
- Consumes: なし
- Produces: `photos.is_allowed(url: str) -> bool`、`photos.attribution(url: str) -> str`、`photos.download(url: str, dest: Path) -> dict`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_photos.py`:

```python
import pytest

from scripts.photos import attribution, is_allowed


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
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_photos.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.photos'`

- [ ] **Step 3: 実装を書く**

`scripts/photos.py`:

```python
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
```

`scripts/fetch_photo.py`:

```python
#!/usr/bin/env python3
"""画像を1枚落として work/<id>/ に置く。

  python scripts/fetch_photo.py work/<id> <画像URL>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.photos import download  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    ap.add_argument("url")
    a = ap.parse_args()

    rec = download(a.url, a.workdir / "photo.jpg")
    (a.workdir / "license.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ {rec['file']}\n{rec['attribution']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_photos.py -v`
Expected: PASS（11件）

- [ ] **Step 5: コミット**

```bash
git add scripts/photos.py scripts/fetch_photo.py tests/test_photos.py
git commit -m "feat: 画像の取得元をホワイトリストで縛る"
```

---

### Task 6: RSS収集と題材スコアリング

**Files:**
- Create: `scripts/sources.py`
- Create: `scripts/collect_news.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: なし
- Produces: `sources.FEEDS: tuple[str, ...]`、`sources.score(title: str) -> int`、`sources.parse_feed(xml: str) -> list[dict]`、`sources.make_id(title: str) -> str`、`sources.rank(items: list[dict], seen: set[str]) -> list[dict]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_sources.py`:

```python
from scripts.sources import make_id, parse_feed, rank, score

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>中国軍機が自衛隊機にレーダー照射</title>
    <link>https://www3.nhk.or.jp/news/html/1.html</link>
  </item>
  <item>
    <title>米中ジュネーブ合意で関税削減</title>
    <link>https://www3.nhk.or.jp/news/html/2.html</link>
  </item>
</channel></rss>
"""


def test_RSSからタイトルとリンクを取る():
    got = parse_feed(FEED_XML)
    assert [i["title"] for i in got] == [
        "中国軍機が自衛隊機にレーダー照射", "米中ジュネーブ合意で関税削減"]
    assert got[0]["link"].startswith("https://")


def test_対中外交や国内政治は加点される():
    assert score("中国軍機が自衛隊機にレーダー照射") > 0
    assert score("高市総理が永住許可要件を厳格化") > 0


def test_日本の当事者性が薄い題材は減点される():
    # 実測で下位に沈んだ型。米中間の話だけで日本が出てこない
    assert score("米中ジュネーブ合意で関税削減") < score("中国軍機が自衛隊機に照射")


def test_同じタイトルは同じIDになる():
    assert make_id("中国軍機が照射") == make_id("中国軍機が照射")
    assert make_id("A") != make_id("B")


def test_既出は除外され高得点順に並ぶ():
    items = parse_feed(FEED_XML)
    got = rank(items, seen=set())
    assert got[0]["title"] == "中国軍機が自衛隊機にレーダー照射"

    seen = {make_id(items[0]["title"])}
    assert all(i["title"] != items[0]["title"] for i in rank(items, seen))
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.sources'`

- [ ] **Step 3: 実装を書く**

`scripts/sources.py`:

```python
#!/usr/bin/env python3
"""題材の発見。

**RSSは「何が起きたか」を知るためだけに使い、記事の文章は台本に渡さない。**
内容は後段で一次資料から書き起こすので、記事の翻案にならない。

配点は既存48本の実績に合わせた。伸びたのは対中外交・政治家の発言・
国内政策で、日本の当事者性が薄い題材（米中貿易など）は実測で下位に沈んだ。
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET

FEEDS = (
    "https://www3.nhk.or.jp/rss/news/cat0.xml",   # 主要
    "https://www3.nhk.or.jp/rss/news/cat4.xml",   # 政治
    "https://news.yahoo.co.jp/rss/topics/domestic.xml",
)

PLUS = {
    "中国": 4, "台湾": 3, "外交": 3, "防衛": 3, "自衛隊": 3, "国連": 2,
    "総理": 3, "大臣": 2, "国会": 2, "議員": 2, "答弁": 3, "発言": 2,
    "炎上": 3, "批判": 2, "撤回": 2, "謝罪": 2, "矛盾": 3,
    "外国人": 3, "税": 2, "物価": 2, "年金": 2, "移民": 3,
}
MINUS = {"米中": 4, "欧州": 2, "アフリカ": 3, "中南米": 3, "スポーツ": 4, "芸能": 3}
JAPAN = ("日本", "国内", "政府", "総理", "自衛隊", "国会", "円")


def score(title: str) -> int:
    s = sum(w for k, w in PLUS.items() if k in title)
    s -= sum(w for k, w in MINUS.items() if k in title)
    if not any(k in title for k in JAPAN):
        s -= 2                      # 日本が出てこない題材は伸びない
    return s


def make_id(title: str) -> str:
    return hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]


def _keyword(title: str) -> str:
    """一次資料を引くための検索語。記号と定型の飾りを落とす。"""
    t = re.sub(r"[【】\[\]（）()「」『』｜|…、。！？!?]", " ", title)
    return " ".join(t.split())[:40]


def parse_feed(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    out: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title and link:
            out.append({"title": title, "link": link})
    return out


def rank(items: list[dict], seen: set[str]) -> list[dict]:
    """既出を除き、得点の高い順に並べる。"""
    out: list[dict] = []
    for it in items:
        nid = make_id(it["title"])
        if nid in seen:
            continue
        seen.add(nid)               # 同一実行内の重複も落とす
        out.append({
            "id": nid,
            "title": it["title"],
            "link": it["link"],
            "keyword": _keyword(it["title"]),
            "category": "政治",
            "score": score(it["title"]),
        })
    return sorted(out, key=lambda x: x["score"], reverse=True)
```

`scripts/collect_news.py`:

```python
#!/usr/bin/env python3
"""RSSを巡回して候補を作る。

  python scripts/collect_news.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SEEN = ROOT / "state" / "seen.json"
OUT = ROOT / "work" / "candidates.json"

from scripts.sources import FEEDS, parse_feed, rank  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))
               if SEEN.exists() else [])

    items: list[dict] = []
    for url in FEEDS:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            items.extend(parse_feed(r.text))
        except Exception as e:            # noqa: BLE001
            print(f"! RSSの取得に失敗しました（このフィードは飛ばします）: {url} {e}")

    picked = rank(items, seen)[:a.limit]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(picked, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"✓ 候補 {len(picked)} 件 → {OUT.name}")
    for p in picked[:5]:
        print(f"  {p['score']:+3d} {p['title'][:40]}")


if __name__ == "__main__":
    main()
```

> `seen.json` の更新は投稿が成功した時点で `run_daily.py` が行う。
> ここで書くと、採用されなかった候補まで二度と扱えなくなる。

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_sources.py -v`
Expected: PASS（5件）

- [ ] **Step 5: 実際のRSSに当てて疎通を確かめる**

Run: `python scripts/collect_news.py --limit 20`
Expected: 候補が20件前後出て、上位に政治・外交の見出しが並ぶ。

- [ ] **Step 6: コミット**

```bash
git add scripts/sources.py scripts/collect_news.py tests/test_sources.py
git commit -m "feat: RSS収集と題材スコアリングを追加"
```

---

### Task 7: 台本生成

**Files:**
- Create: `scripts/script_writer.py`
- Create: `scripts/write_script.py`
- Test: `tests/test_script_writer.py`

**Interfaces:**
- Consumes: `evidence.Evidence`
- Produces: `script_writer.Script`（Pydantic: `title: str`, `narration: str`, `headline: str`, `figure_label: str`, `figure_value: str`, `tags: list[str]`）、`script_writer.build_prompt(recipe: dict) -> str`、`script_writer.write(recipe: dict) -> Script`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_script_writer.py`:

```python
from scripts.script_writer import build_prompt

RECIPE = {
    "id": "abc123",
    "headline": "野田代表が議員定数削減で発言",
    "keyword": "議員定数 削減",
    "category": "政治",
    "evidence": {
        "kind": "speech",
        "source_url": "https://kokkai.ndl.go.jp/#/detail?x=1",
        "figure": "",
        "quote": "私どもは議員定数を四十五削減すると申し上げてまいりました。",
        "context": "第217回国会 衆議院予算委員会 2025-11-20 野田佳彦",
    },
}


def test_一次資料の引用と出典がプロンプトに入る():
    got = build_prompt(RECIPE)
    assert "私どもは議員定数を四十五削減する" in got
    assert "kokkai.ndl.go.jp" in got
    assert "第217回国会" in got


def test_RSSのリンクはプロンプトに渡さない():
    # 記事本文を渡すと翻案になる。渡すのは一次資料だけ
    recipe = dict(RECIPE, link="https://www3.nhk.or.jp/news/html/1.html")
    assert "nhk.or.jp" not in build_prompt(recipe)


def test_尺の指示が入る():
    got = build_prompt(RECIPE)
    assert "350" in got and "400" in got
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_script_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.script_writer'`

- [ ] **Step 3: 実装を書く**

`scripts/script_writer.py`:

```python
#!/usr/bin/env python3
"""台本の生成。

**渡すのは一次資料の抜粋だけ。** RSSの記事本文もリンクも渡さない。
記事を言い換えると翻案になるうえ、YouTube の量産型判定にも近づく。
書かせるのは「ニュースの要約」ではなく「この数字/この発言をどう読むか」。
"""

from __future__ import annotations

from anthropic import Anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

SYSTEM = """あなたは日本の政治・外交ニュースを扱う解説チャンネルの構成作家です。
与えられた一次資料（国会会議録の逐語引用、または政府統計）だけを根拠に、
60秒のショート動画の台本を書きます。

守ること:
- 一次資料に書かれていない事実を足さない。推測を断定で書かない。
- ニュースの要約ではなく、その発言・その数字が何を意味するかの解説にする。
- 話し言葉。ナレーションとしてそのまま読める文章にする。
- 特定の個人や団体への誹謗中傷、断定的な違法行為の指摘は書かない。
"""


class Script(BaseModel):
    title: str = Field(description="YouTubeのタイトル。60文字以内。ハッシュタグは含めない")
    headline: str = Field(description="画面上部に出す見出し。20文字以内")
    narration: str = Field(description="読み上げる本文。350〜400字")
    figure_label: str = Field(description="数値カードの見出し。10文字以内")
    figure_value: str = Field(description="数値カードに大きく出す値。12文字以内")
    tags: list[str] = Field(description="YouTubeのタグ。3〜6個")


def build_prompt(recipe: dict) -> str:
    ev = recipe["evidence"]
    parts = [
        f"題材: {recipe['headline']}",
        "",
        "一次資料:",
        f"  種別: {ev['kind']}",
        f"  出典: {ev['source_url']}",
        f"  文脈: {ev['context']}",
    ]
    if ev.get("quote"):
        parts.append(f"  逐語引用: 「{ev['quote']}」")
    if ev.get("figure"):
        parts.append(f"  数値: {ev['figure']}")
    parts += [
        "",
        "この一次資料だけを根拠に、60秒（350〜400字）のナレーションを書いてください。",
        "figure_value には、視聴者が一目で分かる数字か短い言葉を入れてください。",
    ]
    return "\n".join(parts)


def write(recipe: dict) -> Script:
    client = Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": build_prompt(recipe)}],
        output_format=Script,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"台本生成が拒否されました: {response.stop_details}")
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("台本を構造化出力として受け取れませんでした")
    return parsed
```

`scripts/write_script.py`:

```python
#!/usr/bin/env python3
"""レシピから台本を作って work/<id>/script.json に置く。

  python scripts/write_script.py recipes/<id>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

from scripts.script_writer import write  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", type=Path)
    a = ap.parse_args()

    recipe = json.loads(a.recipe.read_text(encoding="utf-8"))
    script = write(recipe)

    workdir = ROOT / "work" / recipe["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "script.json").write_text(
        script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"✓ {script.title}")
    print(f"  {len(script.narration)}字 / {script.figure_label}: {script.figure_value}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: pydantic を依存に足す**

`requirements.txt` に `pydantic` を追記する。

Run: `pip install -r requirements.txt`

- [ ] **Step 5: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_script_writer.py -v`
Expected: PASS（3件）

- [ ] **Step 6: 実際に1本生成して字数と内容を目視する**

Run:

```bash
python scripts/write_script.py recipes/<Task4で作ったid>.json
```

Expected: 350〜400字の台本が出る。字数が大きく外れるなら `Script.narration` の
`description` を調整する（プロンプト本文ではなくスキーマ側で締めるほうが効く）。

- [ ] **Step 7: コミット**

```bash
git add scripts/script_writer.py scripts/write_script.py tests/test_script_writer.py requirements.txt
git commit -m "feat: 一次資料だけを渡して台本を生成する"
```

---

### Task 8: 描画（縦型フレームと数値カード）

**Files:**
- Create: `scripts/draw.py`
- Create: `scripts/cards.py`
- Test: `tests/test_cards.py`

**Interfaces:**
- Consumes: なし
- Produces: `cards.SHORT_SIZE`, `cards.HOLE_TOP`, `cards.HOLE_BOTTOM`, `cards.render_frame(headline: str, subtitle: str) -> Image`、`cards.render_figure(label: str, value: str, source: str) -> Image`

- [ ] **Step 1: 共通部品を移植する**

`scripts/draw.py` — `tora-kirinuki/scripts/draw.py` をそのままコピーし、配色だけ差し替える:

```python
#!/usr/bin/env python3
"""描画の共通部品。tora-kirinuki/scripts/draw.py から移植した。

配色はニュース向けに、濃紺地に白、差し色に赤。
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageDraw, ImageFont

FONT_SANS = [
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]

NAVY = (16, 24, 43)
RED = (232, 48, 52)
INK = (250, 250, 252)
MUTED = (150, 158, 176)


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_SANS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: int,
             start: int) -> ImageFont.FreeTypeFont:
    """幅に収まる最大サイズのフォントを返す。"""
    size = start
    while size > 14:
        f = pick_font(size)
        b = draw.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= max_w:
            return f
        size -= 2
    return pick_font(14)


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
         max_w: int) -> list[str]:
    """日本語は単語境界が無いので、幅を見て1文字ずつ折り返す。"""
    lines, cur = [], ""
    for ch in text:
        b = draw.textbbox((0, 0), cur + ch, font=font)
        if b[2] - b[0] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_cards.py`:

```python
from scripts.cards import (HOLE_BOTTOM, HOLE_TOP, SHORT_SIZE, render_figure,
                           render_frame)


def test_フレームは縦型で中央が透過している():
    img = render_frame("中国軍機が照射", "レーダー照射は攻撃の一歩手前")
    assert img.size == SHORT_SIZE
    assert img.mode == "RGBA"

    w, _ = SHORT_SIZE
    # 上下の帯は不透明、中央の穴は透過
    assert img.getpixel((w // 2, HOLE_TOP - 20))[3] == 255
    assert img.getpixel((w // 2, (HOLE_TOP + HOLE_BOTTOM) // 2))[3] == 0
    assert img.getpixel((w // 2, HOLE_BOTTOM + 20))[3] == 255


def test_数値カードは穴の下側の大きさで返る():
    img = render_figure("削減数", "45", "国会会議録")
    assert img.size[0] == SHORT_SIZE[0]
    assert img.size[1] == HOLE_BOTTOM - (HOLE_TOP + 659)


def test_長い見出しでも例外にならない():
    render_frame("あ" * 60, "い" * 80)
```

- [ ] **Step 3: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_cards.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cards'`

- [ ] **Step 4: 実装を書く**

`scripts/cards.py`:

```python
#!/usr/bin/env python3
"""縦型ショートの描画。

  上部の帯   見出し（2行まで）
  中央の穴   上に実写、下に数値カード
  下部の帯   ナレーションの要点を字幕で

数値カードが「解説」の実体になる。これが無いと画像スライドショーと
見分けがつかず、量産型コンテンツの判定に近づく。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from scripts.draw import INK, MUTED, NAVY, RED, fit_font, pick_font, wrap

SHORT_SIZE = (1080, 1920)
HOLE_TOP = 460            # 上帯の高さ
HOLE_BOTTOM = 1460        # 下帯の始まり
PHOTO_H = 659             # 穴のうち実写が占める高さ
FIGURE_H = HOLE_BOTTOM - (HOLE_TOP + PHOTO_H)


def render_frame(headline: str, subtitle: str) -> Image.Image:
    """上下の帯を描き、中央を透過にして返す。"""
    w, h = SHORT_SIZE
    img = Image.new("RGBA", SHORT_SIZE, NAVY + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([0, HOLE_TOP, w, HOLE_BOTTOM], fill=(0, 0, 0, 0))

    m = int(w * 0.06)
    avail = w - m * 2

    f = fit_font(d, headline[:20], avail, 92)
    y = 96
    for ln in wrap(d, headline, f, avail)[:2]:
        d.text((m, y), ln, font=f, fill=INK + (255,),
               stroke_width=8, stroke_fill=(0, 0, 0, 255))
        d.text((m, y), ln, font=f, fill=INK + (255,))
        y += int(f.size * 1.26)

    d.rectangle([m, HOLE_BOTTOM + 40, m + 120, HOLE_BOTTOM + 48],
                fill=RED + (255,))

    fs = pick_font(58)
    y = HOLE_BOTTOM + 84
    for ln in wrap(d, subtitle, fs, avail)[:4]:
        d.text((m, y), ln, font=fs, fill=INK + (255,))
        y += 76
    return img


def render_figure(label: str, value: str, source: str) -> Image.Image:
    """数値カード。穴の下側にぴったり収まる大きさで返す。"""
    w = SHORT_SIZE[0]
    img = Image.new("RGB", (w, FIGURE_H), NAVY)
    d = ImageDraw.Draw(img)
    m = int(w * 0.06)
    avail = w - m * 2

    d.rectangle([0, 0, w, 6], fill=RED)
    d.text((m, 28), label, font=pick_font(44), fill=MUTED)

    f = fit_font(d, value, avail, 150)
    d.text((m, 92), value, font=f, fill=INK)

    d.text((m, FIGURE_H - 56), f"出典: {source}", font=pick_font(34), fill=MUTED)
    return img
```

- [ ] **Step 5: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_cards.py -v`
Expected: PASS（3件）

- [ ] **Step 6: 目視で確認する**

Run:

```bash
python -c "from scripts.cards import render_frame; render_frame('中国軍機が自衛隊機に照射','レーダー照射は攻撃の一歩手前とされる').save('_frame.png')"
```

`_frame.png` を開いて、見出しが読めること・穴の位置が中央にあることを確認する。
確認したら削除する。

- [ ] **Step 7: コミット**

```bash
git add scripts/draw.py scripts/cards.py tests/test_cards.py
git commit -m "feat: 縦型フレームと数値カードの描画を追加"
```

---

### Task 9: VOICEVOX でナレーションを作る

**Files:**
- Create: `scripts/narrate.py`
- Test: `tests/test_narrate.py`

**Interfaces:**
- Consumes: なし
- Produces: `narrate.SPEAKER_NAME`、`narrate.resolve_speaker(speakers: list[dict], name: str) -> int`、`narrate.synthesize(text: str, dest: Path) -> Path`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_narrate.py`:

```python
import pytest

from scripts.narrate import resolve_speaker

SPEAKERS = [
    {"name": "四国めたん", "styles": [{"name": "ノーマル", "id": 2}]},
    {"name": "青山龍星", "styles": [
        {"name": "ノーマル", "id": 13},
        {"name": "熱血", "id": 81},
    ]},
]


def test_名前からノーマルの話者IDを引く():
    assert resolve_speaker(SPEAKERS, "青山龍星") == 13


def test_居ない話者は例外にする():
    # 黙って別の声で作ると、既存視聴者の耳と合わない動画が公開される
    with pytest.raises(ValueError, match="見つかりません"):
        resolve_speaker(SPEAKERS, "存在しない話者")
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_narrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.narrate'`

- [ ] **Step 3: 実装を書く**

`scripts/narrate.py`:

```python
#!/usr/bin/env python3
"""VOICEVOX のローカルエンジンでナレーションを合成する。

話者は**青山龍星**。既存2,845人の耳に合っている声なので変えない。
話者IDはバージョンで変わりうるのでハードコードせず、名前から引く。

  python scripts/narrate.py work/<id>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ENGINE = "http://127.0.0.1:50021"
SPEAKER_NAME = "青山龍星"
STYLE_NAME = "ノーマル"
TIMEOUT = 120


def resolve_speaker(speakers: list[dict], name: str,
                    style: str = STYLE_NAME) -> int:
    for sp in speakers:
        if sp.get("name") != name:
            continue
        for st in sp.get("styles") or []:
            if st.get("name") == style:
                return int(st["id"])
    raise ValueError(f"話者が見つかりません: {name}／{style}")


def ensure_engine() -> None:
    """エンジンの応答を確かめ、無ければ起動を試みる。

    ここで止めないと、後段が無音の動画を作って上げてしまう。
    """
    try:
        requests.get(f"{ENGINE}/version", timeout=5).raise_for_status()
        return
    except Exception:                     # noqa: BLE001
        pass

    exe = Path(r"C:\Program Files\VOICEVOX\VOICEVOX.exe")
    if exe.exists():
        print("- VOICEVOX が応答しないので起動します")
        subprocess.Popen([str(exe)])
        for _ in range(30):
            time.sleep(2)
            try:
                requests.get(f"{ENGINE}/version", timeout=5).raise_for_status()
                return
            except Exception:             # noqa: BLE001
                continue
    raise RuntimeError(f"VOICEVOX のエンジンに接続できません: {ENGINE}")


def _speaker_id() -> int:
    r = requests.get(f"{ENGINE}/speakers", timeout=TIMEOUT)
    r.raise_for_status()
    return resolve_speaker(r.json(), SPEAKER_NAME)


def synthesize(text: str, dest: Path) -> Path:
    """text を読み上げた wav を dest に書く。"""
    ensure_engine()
    sid = _speaker_id()
    q = requests.post(f"{ENGINE}/audio_query", timeout=TIMEOUT,
                      params={"text": text, "speaker": sid})
    q.raise_for_status()
    query = q.json()
    query["speedScale"] = 1.15        # 60秒に400字を収めるため少し速める

    s = requests.post(f"{ENGINE}/synthesis", timeout=TIMEOUT,
                      params={"speaker": sid}, json=query)
    s.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(s.content)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    a = ap.parse_args()

    script = json.loads((a.workdir / "script.json").read_text(encoding="utf-8"))
    out = synthesize(script["narration"], a.workdir / "voice.wav")
    print(f"✓ {out.name}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_narrate.py -v`
Expected: PASS（2件）

- [ ] **Step 5: VOICEVOX を起動して実際に合成する**

VOICEVOX アプリを起動してから:

```bash
python scripts/narrate.py work/<Task7で作ったid>
```

Expected: `voice.wav` ができる。再生して声が青山龍星であること、
尺が56〜61秒に収まることを確認する。外れるなら `speedScale` を調整する。

- [ ] **Step 6: コミット**

```bash
git add scripts/narrate.py tests/test_narrate.py
git commit -m "feat: VOICEVOX でナレーションを合成する"
```

---

### Task 10: 動画を合成する

**Files:**
- Create: `scripts/build_short.py`
- Test: `tests/test_build_short.py`

**Interfaces:**
- Consumes: `cards.render_frame`, `cards.render_figure`, `cards.SHORT_SIZE`, `cards.HOLE_TOP`, `cards.PHOTO_H`
- Produces: `build_short.compose_stage(photo: Path, script: dict, source: str) -> Image`、`build_short.build(workdir: Path) -> Path`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_build_short.py`:

```python
from PIL import Image

from scripts.build_short import compose_stage
from scripts.cards import SHORT_SIZE

SCRIPT = {"headline": "中国軍機が照射", "narration": "レーダー照射は攻撃の一歩手前",
          "figure_label": "照射回数", "figure_value": "1回",
          "title": "t", "tags": []}


def test_下地は縦型の不透明画像になる(tmp_path):
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (1600, 900), (80, 90, 110)).save(photo)

    got = compose_stage(photo, SCRIPT, source="国会会議録")
    assert got.size == SHORT_SIZE
    assert got.mode == "RGB"


def test_縦長の写真でも横幅いっぱいに収まる(tmp_path):
    photo = tmp_path / "tall.jpg"
    Image.new("RGB", (600, 1800), (10, 20, 30)).save(photo)

    got = compose_stage(photo, SCRIPT, source="e-Stat")
    assert got.size == SHORT_SIZE
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python -m pytest tests/test_build_short.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.build_short'`

- [ ] **Step 3: 実装を書く**

`scripts/build_short.py`:

```python
#!/usr/bin/env python3
"""静止画とナレーションから縦型ショートを組む。

  python scripts/build_short.py work/<id>

動きのある編集はしない。1枚の下地に音声を載せるだけにして、
差別化は数値カードの中身に寄せる。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

from scripts.cards import (HOLE_TOP, PHOTO_H, SHORT_SIZE, render_figure,  # noqa: E402
                           render_frame)


def _fill(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """アスペクト比を保ったまま size を覆うように拡大し、中央で切り取る。"""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    left = (resized.width - tw) // 2
    top = (resized.height - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def compose_stage(photo: Path, script: dict, source: str) -> Image.Image:
    """実写＋数値カード＋上下の帯を1枚に焼く。"""
    w, _ = SHORT_SIZE
    stage = Image.new("RGB", SHORT_SIZE, (16, 24, 43))

    with Image.open(photo) as im:
        stage.paste(_fill(im.convert("RGB"), (w, PHOTO_H)), (0, HOLE_TOP))

    figure = render_figure(script["figure_label"], script["figure_value"], source)
    stage.paste(figure, (0, HOLE_TOP + PHOTO_H))

    frame = render_frame(script["headline"], script["narration"])
    stage.paste(frame, (0, 0), frame)
    return stage


def build(workdir: Path) -> Path:
    script = json.loads((workdir / "script.json").read_text(encoding="utf-8"))
    license_ = json.loads((workdir / "license.json").read_text(encoding="utf-8"))
    recipe = json.loads(
        (ROOT / "recipes" / f"{workdir.name}.json").read_text(encoding="utf-8"))
    # 数値カードの脚注に出す。どの一次資料から取った数字かを画面に残す
    source = recipe["evidence"]["context"]

    stage_path = workdir / "stage.png"
    compose_stage(workdir / "photo.jpg", script, source).save(stage_path)

    out = workdir / "video.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(stage_path),
        "-i", str(workdir / "voice.wav"),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(out),
    ], check=True)
    print(f"  画像の出典: {license_['attribution'].splitlines()[0]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    a = ap.parse_args()
    out = build(a.workdir)
    print(f"✓ {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `python -m pytest tests/test_build_short.py -v`
Expected: PASS（2件）

- [ ] **Step 5: 実際に1本組んで尺を測る**

Run:

```bash
python scripts/build_short.py work/<id>
ffprobe -v error -show_entries format=duration -of csv=p=0 work/<id>/video.mp4
```

Expected: 56〜61秒。動画を再生し、見出し・写真・数値カード・字幕が
重ならずに読めることを確認する。

- [ ] **Step 6: コミット**

```bash
git add scripts/build_short.py tests/test_build_short.py
git commit -m "feat: 静止画とナレーションから縦型ショートを組む"
```

---

### Task 11: アップロードと緊急停止

**Files:**
- Create: `scripts/upload_youtube.py`（`tora-kirinuki` から移植）
- Create: `scripts/unpublish.py`
- Create: `state/published.json`

**Interfaces:**
- Consumes: `work/<id>/video.mp4`, `work/<id>/meta.json`, `work/<id>/description.txt`
- Produces: `upload_youtube` CLI（`--auth-only` / `--schedule ISO8601` / `--publish`）、`unpublish` CLI

- [ ] **Step 1: upload_youtube.py を移植する**

`tora-kirinuki/scripts/upload_youtube.py` をコピーし、以下だけ変える。

- モジュール冒頭の docstring を news-youtube 用に書き直す（ガジェット通信の許諾に関する記述を削除する）
- それ以外（`SCOPES`, `assert_expected_channel`, `set_privacy` の `publish_at` 対応, `record`）はそのまま使う

```bash
cp ../tora-kirinuki/scripts/upload_youtube.py scripts/upload_youtube.py
```

コピー後、冒頭のdocstringを次に差し替える:

```python
"""ビルドしたショートを YouTube に上げる。

  python scripts/upload_youtube.py --auth-only                      # 初回の認証だけ
  python scripts/upload_youtube.py work/<id>                        # private で投稿
  python scripts/upload_youtube.py work/<id> --schedule 2026-08-11T07:30:00+09:00

tora-kirinuki/scripts/upload_youtube.py から移植した。
チャンネル取り違えのガードと予約公開はそのまま持ってきている。
"""
```

- [ ] **Step 2: 認証を通してチャンネルを確認する**

Google Cloud で YouTube Data API v3 を有効化し、OAuth クライアント（デスクトップアプリ）の
`client_secret.json` をリポジトリ直下に置いてから:

Run: `python scripts/upload_youtube.py --auth-only`
Expected: `✓ 認証しました: 日本の最新ニュースまるわかり（UCYHTfHJOoETzvpx-VZlUTng）`

別のチャンネル名が出たら、同意画面で選び直す（`token.json` を消してやり直す）。

- [ ] **Step 3: 緊急停止のスクリプトを書く**

`scripts/unpublish.py`:

```python
#!/usr/bin/env python3
"""公開済みの動画を非公開に戻す。

  python scripts/unpublish.py <video_id>
  python scripts/unpublish.py --all-today

完全自動で公開しているので、事後に問題が判明したときの手段が要る。
これが唯一の保険なので、依存を増やさず単体で動くようにしてある。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "state" / "published.json"

from scripts.upload_youtube import get_service, set_privacy  # noqa: E402


def _today_ids() -> list[str]:
    data = json.loads(PUBLISHED.read_text(encoding="utf-8-sig"))
    today = date.today().isoformat()
    return [v["youtube_video_id"] for v in data.get("videos", {}).values()
            if (v.get("publish_at") or "").startswith(today)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id", nargs="?")
    ap.add_argument("--all-today", action="store_true")
    a = ap.parse_args()

    ids = _today_ids() if a.all_today else ([a.video_id] if a.video_id else [])
    if not ids:
        print("対象がありません")
        return

    service = get_service()
    for vid in ids:
        set_privacy(service, vid, "private")
        print(f"✓ 非公開に戻しました: https://www.youtube.com/watch?v={vid}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 空の published.json を置く**

`state/published.json`:

```json
{
  "videos": {}
}
```

- [ ] **Step 5: private で1本上げて、非公開に戻せることを確かめる**

`work/<id>/meta.json` を手で作る:

```json
{
  "id": "<id>",
  "title": "<script.json の title>",
  "tags": ["政治", "外交"],
  "category_id": "25",
  "expected_channel_id": "UCYHTfHJOoETzvpx-VZlUTng",
  "privacy_status": "private"
}
```

`work/<id>/description.txt` に `license.json` の `attribution` と一次資料のURLを書く。

```bash
python scripts/upload_youtube.py work/<id>
python scripts/unpublish.py <出力された video_id>
```

Expected: アップロードされ、その後 private に戻る。Studio で確認する。

- [ ] **Step 6: コミット**

```bash
git add scripts/upload_youtube.py scripts/unpublish.py state/published.json
git commit -m "feat: アップロードと緊急停止を追加"
```

---

### Task 12: オーケストレータと定期実行

**Files:**
- Create: `scripts/run_daily.py`
- Create: `docs/daily-workflow.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: 全モジュール
- Produces: `run_daily.py` CLI（`--dry-run`）

- [ ] **Step 1: オーケストレータを書く**

`scripts/run_daily.py`:

```python
#!/usr/bin/env python3
"""1日分を作って予約公開まで通す。

  python scripts/run_daily.py
  python scripts/run_daily.py --dry-run   # アップロードだけ飛ばす

タスクスケジューラから毎朝1回呼ばれる。当日のまだ来ていない枠の数だけ作り、
YouTube側の予約公開に載せて終わる。PCが日中落ちていても定刻に公開される。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SEEN = ROOT / "state" / "seen.json"
STREAK = ROOT / "state" / "empty_streak.json"
CHANNEL_ID = "UCYHTfHJOoETzvpx-VZlUTng"

from scripts.build_short import build  # noqa: E402
from scripts.evidence import collect  # noqa: E402
from scripts.narrate import synthesize  # noqa: E402
from scripts.script_writer import write  # noqa: E402
from scripts.slots import pending_slots  # noqa: E402


def _bump_empty_streak(made: int) -> None:
    """0本の日が続いたら警告する。収益化要件は90日で3本以上。"""
    n = 0 if made else (json.loads(STREAK.read_text(encoding="utf-8"))["days"]
                        if STREAK.exists() else 0) + 1
    STREAK.write_text(json.dumps({"days": n}) + "\n", encoding="utf-8")
    if n >= 3:
        print(f"! {n}日続けて0本です。RSSの配点か採用ゲートを見直してください")


def _write_meta(workdir: Path, script, license_: dict, evidence: dict) -> None:
    (workdir / "meta.json").write_text(json.dumps({
        "id": workdir.name,
        "title": script.title[:100],
        "tags": script.tags,
        "category_id": "25",
        "expected_channel_id": CHANNEL_ID,
        "privacy_status": "private",
        "source_url": evidence["source_url"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (workdir / "description.txt").write_text("\n".join([
        script.narration,
        "",
        f"根拠: {evidence['context']}",
        evidence["source_url"],
        "",
        license_["attribution"],
    ]) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    slots = pending_slots(datetime.now())
    if not slots:
        print("本日の枠は過ぎています。明朝に回します")
        return
    print(f"- 本日の残り枠: {[s.strftime('%H:%M') for s in slots]}")

    subprocess.run([sys.executable, "scripts/collect_news.py",
                    "--limit", "20"], check=True, cwd=ROOT)
    candidates = json.loads(
        (ROOT / "work" / "candidates.json").read_text(encoding="utf-8"))

    seen = set(json.loads(SEEN.read_text(encoding="utf-8"))
               if SEEN.exists() else [])
    made = 0

    for cand in candidates:
        if made >= len(slots):
            break
        found = collect(cand["keyword"])
        if not found:
            continue
        ev = found[0]

        workdir = ROOT / "work" / cand["id"]
        workdir.mkdir(parents=True, exist_ok=True)
        recipe = {"id": cand["id"], "headline": cand["title"],
                  "keyword": cand["keyword"], "category": cand["category"],
                  "evidence": ev.__dict__}
        (ROOT / "recipes" / f"{cand['id']}.json").write_text(
            json.dumps(recipe, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

        # 1本の失敗で当日を全部落とさない。work/ は残るので次回リトライできる
        try:
            script = write(recipe)
            synthesize(script.narration, workdir / "voice.wav")
            license_ = json.loads(
                (workdir / "license.json").read_text(encoding="utf-8"))
            (workdir / "script.json").write_text(
                script.model_dump_json(indent=2) + "\n", encoding="utf-8")
            _write_meta(workdir, script, license_, ev.__dict__)
            build(workdir)

            if not a.dry_run:
                subprocess.run([sys.executable, "scripts/upload_youtube.py",
                                str(workdir)], check=True, cwd=ROOT)
                subprocess.run([sys.executable, "scripts/upload_youtube.py",
                                str(workdir), "--schedule",
                                slots[made].strftime("%Y-%m-%dT%H:%M:%S+09:00")],
                               check=True, cwd=ROOT)
        except Exception as e:            # noqa: BLE001
            print(f"! 失敗しました（この題材は飛ばします）: {cand['id']} {e}")
            continue

        # 投稿が通ってから既出に入れる。失敗した題材は次回また拾えるようにする
        seen.add(cand["id"])
        made += 1
        print(f"✓ {made}/{len(slots)} {script.title[:40]}")

    SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"本日 {made}/{len(slots)} 本")
    _bump_empty_streak(made)


if __name__ == "__main__":
    main()
```

> 画像の取得は題材ごとに人物・場面が違うため、`fetch_photo.py` を手で当てて
> `work/<id>/photo.jpg` と `license.json` を用意しておく段取りにしている。
> ここを無人化するには「題材 → 官邸/Commons の画像URL」の解決が要る。
> 採用率が実測できてから別タスクで足す。

- [ ] **Step 2: dry-run で通しを確認する**

Run: `python scripts/run_daily.py --dry-run`
Expected: 候補収集 → 採用 → 台本 → 音声 → 合成 まで通り、`work/<id>/video.mp4` ができる。
どこかで落ちたらそのタスクに戻る。

- [ ] **Step 3: 全テストを実行する**

Run: `python -m pytest -v`
Expected: PASS（全件）

- [ ] **Step 4: 運用手順を書く**

`docs/daily-workflow.md`:

```markdown
# 毎日の手順

## 自動で走るもの

タスクスケジューラが毎朝 06:00 に `run_daily.py` を起動する。
当日の残り枠の数だけ作り、07:30 / 18:30 の予約公開に載せて終わる。
PC が日中落ちていても YouTube 側が定刻に公開する。

## 手で見るもの

- **朝** — 実行ログで「本日 N/2 本」を確認する。0本が3日続くと警告が出る。
- **画像** — 題材ごとに `python scripts/fetch_photo.py work/<id> <URL>` で
  官邸か Commons から1枚落としておく。ホワイトリスト外のURLは弾かれる。

## 事故ったとき

```bash
python scripts/unpublish.py <video_id>   # 1本だけ戻す
python scripts/unpublish.py --all-today  # 当日分を全部戻す
```

## 前提の確認

- VOICEVOX が起動していること（`http://127.0.0.1:50021/speakers` が応答する）
- `ANTHROPIC_API_KEY` と `ESTAT_APP_ID` が環境変数にあること
- `token.json` が `UCYHTfHJOoETzvpx-VZlUTng` に紐づいていること
  （`python scripts/upload_youtube.py --auth-only` で確認できる）
```

- [ ] **Step 5: タスクスケジューラに登録する**

Run（管理者権限のPowerShellで）:

```powershell
schtasks /create /tn "news-youtube" /tr "python C:\Users\oshim\Documents\projects\news-youtube\scripts\run_daily.py" /sc daily /st 06:00 /f
```

Expected: `成功: スケジュール タスク "news-youtube" は正しく作成されました。`

- [ ] **Step 6: README の「状態」を更新する**

`README.md` の末尾を差し替える:

```markdown
## 状態

パイプライン実装済み。毎朝06:00にタスクスケジューラから実行される。
画像の取得だけ手で当てる（`fetch_photo.py`）。
```

- [ ] **Step 7: コミット**

```bash
git add scripts/run_daily.py docs/daily-workflow.md README.md
git commit -m "feat: オーケストレータと定期実行を追加"
git push
```

---

## 実装後に残る宿題

計画に含めていないが、稼働後に効いてくるもの。

1. **画像取得の無人化** — 「題材 → 画像URL」の解決。官邸の写真一覧と
   Commons の検索APIを当てる。採用率が実測できてから設計する。
2. **報道発表（3系統目）** — 府省ごとにHTML構造が違うので汎用実装が持てない。
   2系統での採用率を見てから、省庁を絞って足す。
3. **タイトルへの再生数追記** — 既存48本がやっていた `㊗️N回再生！` の運用。
   伸びた後に付ける処理なので、投稿パイプラインとは別サイクル。
