# 24時間ライブ配信（ニュースラジオ）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一次資料の逐語引用だけを読み上げる16:9のループ動画を作り、11.5時間ごとに配信枠を差し替えながら24時間流し続ける。

**Architecture:** 入力は `recipes/*.json`（採用ゲート通過済み）だけ。`build_live_loop.py` が約40分の `loop.mp4` を1本作り、`run_live.py` が ffmpeg を常駐させて RTMP に流しつつ、YouTube の配信枠だけを11.5時間ごとに作り直す。ffmpeg は原則止めない。

**Tech Stack:** Python 3.13 / ffmpeg 9.0 / VOICEVOX（`narrate.py`）/ YouTube Data API v3（`liveBroadcasts` / `liveStreams`）/ Pillow

**Spec:** [`docs/superpowers/specs/2026-09-09-live-streaming-design.md`](../specs/2026-09-09-live-streaming-design.md)

## Global Constraints

これらは**全タスクの要件に暗黙に含まれる**。

- **入力は `recipes/*.json` だけ。** ライブ経路で新しい題材を取りに行かない。採用ゲート（`evidence.collect()`）を再実装しない。
- **読み上げるのは3つだけ**: `headline` / `evidence.quote`（逐語）/ `evidence.context` と `evidence.source_url`。**モデルに1文字も書かせない。**
- **BGM の関門を新設しない。** `scripts/audio_mix.py` の `mix(voice_path, out_path, *, bgm_path=None) -> MixReport` を通す。
- **写真を使わない。**
- **12時間を超える配信を作れる経路を残さない。** 超えるとアーカイブが作られず、再生時間は1分も4,000時間に入らない。
- **関門は呼び出し側に置かない。** 枠を作る関数の中に1箇所ずつ。
- **`state/live.json` を手で編集しない。**
- テスト関数名は日本語（既存の `tests/test_audio_mix.py` に合わせる）。
- 既存ファイルを変更しない。新規は `scripts/build_live_loop.py` / `scripts/run_live.py` / `tests/test_build_live_loop.py` / `tests/test_run_live.py` の4つだけ。

## File Structure

| ファイル | 責務 |
|---|---|
| `scripts/build_live_loop.py` | レシピ選定 → 台本 → 描画 → `work/live/loop.mp4` を1本作る |
| `scripts/run_live.py` | 配信枠のローテーション・二重起動ロック・ffmpeg の常駐 |
| `tests/test_build_live_loop.py` | 選定・台本・逐語保証のテスト |
| `tests/test_run_live.py` | ローテーション判定・二重起動ロックのテスト |
| `state/live.json` | 現在の broadcast id / stream id / 枠の開始時刻（実行時に生成） |

---

### Task 1: 前提の実測（アーカイブが `videoOnDemand` に計上されるか）

**このタスクだけコードを書かない。** 設計全体がこの1点の推定に乗っているので、実装より先に測る。**外れたら以降のタスクを全部破棄する。**

> ⚠ **公開ライブ配信は外向きの行為。** 実行前に必ずオーナーの明示的な承認を取ること。無断で流さない。

**Files:** なし（`docs/` に結果を追記するのみ）

**Interfaces:**
- Consumes: なし
- Produces: 「アーカイブが計上される／されない」という判定。以降の全タスクの前提。

- [ ] **Step 1: 現在地を記録する**

Run:
```bash
python -c "
import sys, datetime; sys.path.insert(0,'scripts')
from upload_youtube import get_credentials
from googleapiclient.discovery import build
an = build('youtubeAnalytics','v2',credentials=get_credentials())
end = datetime.date.today(); start = end - datetime.timedelta(days=365)
r = an.reports().query(ids='channel==MINE', startDate=str(start), endDate=str(end),
    metrics='estimatedMinutesWatched,views', dimensions='creatorContentType').execute()
for row in r.get('rows', []): print(f'{row[0]:18} {row[1]/60:9.1f} h {row[2]:>10,} views')
"
```
Expected: `videoOnDemand` が 0.1 h 前後。**この数字を控える。**

- [ ] **Step 2: 短い公開配信を1本流して終了する**

YouTube Studio の「ライブ配信をスケジュール設定」から**公開**で枠を作り、10〜15分流して終了する。手動でよい（この段階では `run_live.py` はまだ無い）。

- [ ] **Step 3: アーカイブが残ったかを確認する**

Run:
```bash
python -c "
import sys; sys.path.insert(0,'scripts')
from upload_youtube import get_credentials
from googleapiclient.discovery import build
yt = build('youtube','v3',credentials=get_credentials())
r = yt.liveBroadcasts().list(part='id,snippet,status', mine=True, broadcastStatus='completed', maxResults=5).execute()
for it in r.get('items', []):
    print(it['id'], it['status']['lifeCycleStatus'], it['status']['privacyStatus'], it['snippet']['title'])
"
```
Expected: 終了した配信が1件返り、`privacyStatus` が `public`。その video id が通常の動画として再生できること。

- [ ] **Step 4: 数日後にもう一度 Analytics を引く**

Step 1 と同じコマンドを、配信の**3日後以降**に実行する。
Expected: `videoOnDemand` の時間が Step 1 の値から**増えている**。

- [ ] **Step 5: 結果を記録してコミット**

`docs/superpowers/specs/2026-09-09-live-streaming-design.md` の「未確認」節から該当項目を外し、**実際の数字とともに**「検証済み」として書き直す。増えていなければ **STOP** し、以降のタスクを破棄してオーナーに報告する。

```bash
git add docs/superpowers/specs/2026-09-09-live-streaming-design.md
git commit -m "ライブのアーカイブが videoOnDemand に計上されるかを実測した"
```

---

### Task 2: レシピの選定（カテゴリ除外）

**Files:**
- Create: `scripts/build_live_loop.py`
- Test: `tests/test_build_live_loop.py`

**Interfaces:**
- Consumes: `recipes/*.json`（キー `id / headline / keyword / category / evidence`）
- Produces: `select_recipes(recipes_dir: Path, *, exclude_categories: frozenset[str] = frozenset()) -> list[dict]` — `id` 昇順で返す

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_build_live_loop.py
import json
from pathlib import Path

from scripts.build_live_loop import select_recipes


def _recipe(tmp_path: Path, rid: str, category: str) -> None:
    (tmp_path / f"{rid}.json").write_text(json.dumps({
        "id": rid, "headline": f"{rid}の見出し", "keyword": "税",
        "category": category,
        "evidence": {"kind": "speech", "source_url": "https://kokkai.ndl.go.jp/txt/1/1",
                     "figure": "", "quote": "逐語の引用文です。", "context": "第221回国会 2026-05-08 谷浩一郎",
                     "speaker": "谷浩一郎"},
    }, ensure_ascii=False), encoding="utf-8")


def test_レシピをid順に読み込む(tmp_path):
    _recipe(tmp_path, "bbb", "税")
    _recipe(tmp_path, "aaa", "税")
    got = select_recipes(tmp_path)
    assert [r["id"] for r in got] == ["aaa", "bbb"]


def test_除外したカテゴリのレシピは入らない(tmp_path):
    _recipe(tmp_path, "aaa", "税")
    _recipe(tmp_path, "bbb", "選挙")
    got = select_recipes(tmp_path, exclude_categories=frozenset({"選挙"}))
    assert [r["id"] for r in got] == ["aaa"]


def test_除外しなければ選挙も入る(tmp_path):
    _recipe(tmp_path, "bbb", "選挙")
    assert len(select_recipes(tmp_path)) == 1
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.build_live_loop'`

- [ ] **Step 3: 最小の実装を書く**

```python
#!/usr/bin/env python3
"""recipes/*.json から常時配信用のループ動画を1本組む。

  python scripts/build_live_loop.py --out work/live/loop.mp4

読み上げるのは 見出し / 一次資料の逐語引用 / 出典 の3つだけ。
モデルが書いた文字列は1文字も入らない。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = ROOT / "recipes"


def select_recipes(recipes_dir: Path, *,
                   exclude_categories: frozenset[str] = frozenset()) -> list[dict]:
    """ループに載せるレシピを id 昇順で返す。

    `exclude_categories` は投票日に選挙関連を外すためにある
    （公職選挙法129条。動き続ける配信は継続的な公開行為にあたる）。
    """
    out = []
    for path in sorted(Path(recipes_dir).glob("*.json")):
        recipe = json.loads(path.read_text(encoding="utf-8"))
        if recipe.get("category") in exclude_categories:
            continue
        out.append(recipe)
    return sorted(out, key=lambda r: r["id"])
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: PASS（3件）

- [ ] **Step 5: コミット**

```bash
git add scripts/build_live_loop.py tests/test_build_live_loop.py
git commit -m "ライブ配信: レシピの選定とカテゴリ除外を追加"
```

---

### Task 3: 読み上げ台本の組み立て（逐語であることを縛る）

**Files:**
- Modify: `scripts/build_live_loop.py`
- Test: `tests/test_build_live_loop.py`

**Interfaces:**
- Consumes: `select_recipes` が返すレシピ辞書
- Produces: `narration_text(recipe: dict) -> str`

- [ ] **Step 1: 失敗するテストを書く**

```python
from scripts.build_live_loop import narration_text

_R = {
    "id": "aaa", "headline": "奨学金の返済が長期化している", "category": "教育",
    "evidence": {"quote": "平均で十五年かけて返済しています。",
                 "context": "第221回国会 衆議院特別委員会 2026-05-08 谷浩一郎",
                 "source_url": "https://kokkai.ndl.go.jp/txt/1/1", "speaker": "谷浩一郎"},
}


def test_見出しと引用と出典がこの順で入る():
    got = narration_text(_R)
    assert got.index("奨学金") < got.index("十五年") < got.index("谷浩一郎")


def test_引用は逐語のまま入る():
    assert _R["evidence"]["quote"] in narration_text(_R)


def test_引用に無い言葉を足さない():
    """台本は見出し・引用・出典の連結だけ。ここに定型の地の文を入れると、
    一次資料に無い文字列が出典付きで読み上げられることになる。"""
    got = narration_text(_R)
    for part in (_R["headline"], _R["evidence"]["quote"], _R["evidence"]["context"]):
        got = got.replace(part, "", 1)
    # 残ってよいのは区切りの句読点と空白だけ
    assert set(got) <= set("。、 \n"), f"余計な地の文が入っている: {got!r}"
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: FAIL — `ImportError: cannot import name 'narration_text'`

- [ ] **Step 3: 最小の実装を書く**

```python
def narration_text(recipe: dict) -> str:
    """読み上げる文字列。**見出し・逐語引用・出典の連結だけ。**

    ここに定型の地の文（「続いてのニュースです」等）を足さないこと。
    足した瞬間、一次資料に無い文字列が出典キャプション付きで読み上げられ、
    「一次資料が取れなければ公開しない」がこの経路だけ破れる。
    """
    ev = recipe["evidence"]
    return "\n".join([recipe["headline"], ev["quote"], ev["context"]])
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: PASS（6件）

- [ ] **Step 5: コミット**

```bash
git add scripts/build_live_loop.py tests/test_build_live_loop.py
git commit -m "ライブ配信: 読み上げ台本を見出し・逐語引用・出典の連結に限る"
```

---

### Task 4: 16:9フレームの描画（写真なし）

**Files:**
- Modify: `scripts/build_live_loop.py`
- Test: `tests/test_build_live_loop.py`

**Interfaces:**
- Consumes: `cards_wide.render_headline(headline: str, number: int = 0) -> Image.Image`、`cards_wide.render_quote(text: str, source: str) -> Image.Image`、`cards_wide.WIDE_SIZE == (1920, 1080)`、`evidence.ground_excerpt(excerpt: str, quote: str) -> str`
- Produces: `render_frame(recipe: dict) -> Image.Image`（1920x1080）

- [ ] **Step 1: 失敗するテストを書く**

```python
from scripts.build_live_loop import render_frame
from scripts.cards_wide import WIDE_SIZE


def test_フレームは1920x1080():
    assert render_frame(_R).size == WIDE_SIZE


def test_引用カードに載せる文字列は一次資料の逐語(monkeypatch):
    """描画に渡した文字列が evidence.ground_excerpt を通っていること。
    通っていなければ、モデル生成値に出典が付く経路がここに開く。"""
    seen = []
    import scripts.build_live_loop as m
    original = m.ground_excerpt
    monkeypatch.setattr(m, "ground_excerpt",
                        lambda excerpt, quote: seen.append((excerpt, quote)) or original(excerpt, quote))
    render_frame(_R)
    assert seen == [(_R["evidence"]["quote"], _R["evidence"]["quote"])]
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_frame'`

- [ ] **Step 3: 最小の実装を書く**

`build_live_loop.py` の import に追記:

```python
from PIL import Image

from scripts.cards_wide import (BODY_TOP, CARD_LEFT, TELOP_TOP,  # noqa: E402
                                WIDE_SIZE, render_headline, render_quote)
from scripts.draw import NAVY  # noqa: E402
from scripts.evidence import ground_excerpt  # noqa: E402
```

```python
def render_frame(recipe: dict) -> Image.Image:
    """1題材ぶんの静止画。**写真枠は使わない。**

    50件ぶんの写真が work/ から消えており、取り直すと人物写真の
    取り違えリスクを新しい経路に持ち込む（CLAUDE.md）。
    """
    ev = recipe["evidence"]
    base = Image.new("RGB", WIDE_SIZE, NAVY)
    base.paste(render_headline(recipe["headline"]), (0, 0))
    # ground_excerpt を通すことで、カードに出る文字列が逐語引用であることを担保する
    quote = ground_excerpt(ev["quote"], ev["quote"])
    base.paste(render_quote(quote, ev["context"]), (CARD_LEFT, BODY_TOP))
    return base
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: PASS（8件）

- [ ] **Step 5: コミット**

```bash
git add scripts/build_live_loop.py tests/test_build_live_loop.py
git commit -m "ライブ配信: 写真を使わない16:9フレームの描画を追加"
```

---

### Task 5: `loop.mp4` のビルド（音声合成 → audio_mix → ffmpeg）

**Files:**
- Modify: `scripts/build_live_loop.py`
- Test: `tests/test_build_live_loop.py`

**Interfaces:**
- Consumes: `narrate.synthesize(text: str, dest: Path, *, target_min: float, target_max: float) -> Path`、`narrate.SECONDS_PER_CHAR == 0.171`、`audio_mix.mix(voice_path: Path, out_path: Path, *, bgm_path: Path | None = None) -> MixReport`
- Produces: `speech_window(text: str) -> tuple[float, float]`、`build(out_path: Path, recipes: list[dict]) -> Path`

`narrate.synthesize` の既定の尺の窓は 56〜61秒（ショート用）に固定されている。ライブの1題材は引用文の長さでばらつくので、**呼び出し側が窓を渡さないと毎回「範囲外」の警告が出て、本物の異常（無音・合成失敗）がその警告に埋もれる。**

- [ ] **Step 1: 失敗するテストを書く**

```python
from scripts.build_live_loop import speech_window
from scripts.narrate import SECONDS_PER_CHAR


def test_尺の窓は文字数から決まる():
    text = "あ" * 200
    lo, hi = speech_window(text)
    est = 200 * SECONDS_PER_CHAR
    assert lo < est < hi


def test_短い題材でも窓が反転しない():
    lo, hi = speech_window("あ")
    assert 0 < lo < hi
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: FAIL — `ImportError: cannot import name 'speech_window'`

- [ ] **Step 3: 最小の実装を書く**

```python
from scripts.narrate import SECONDS_PER_CHAR, synthesize  # noqa: E402
from scripts.audio_mix import mix  # noqa: E402

# 推定尺に対して許容する上下の幅。ショートの 56〜61秒（±4%）より広いのは、
# ライブの1題材が引用文の長さでばらつくため。狭いと毎回警告が出て、
# 無音や合成失敗という本物の異常がその警告に埋もれる。
WINDOW_LOW = 0.70
WINDOW_HIGH = 1.40


def speech_window(text: str) -> tuple[float, float]:
    """`narrate.synthesize` に渡す尺の窓を文字数から決める。"""
    est = max(len(text) * SECONDS_PER_CHAR, 1.0)
    return est * WINDOW_LOW, est * WINDOW_HIGH
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_build_live_loop.py -v`
Expected: PASS（10件）

- [ ] **Step 5: `build()` を実装する**

```python
import subprocess


def build(out_path: Path, recipes: list[dict], *, workdir: Path | None = None) -> Path:
    """レシピを順に読み上げた16:9のループ用 mp4 を1本書き出す。

    配信側は再エンコードしない（`-c copy`）ので、ここで
    YouTube ライブに載る形（h264 + aac・2秒GOP）まで作り切る。
    """
    out_path = Path(out_path)
    work = Path(workdir) if workdir else out_path.parent / "parts"
    work.mkdir(parents=True, exist_ok=True)

    frames, wavs = [], []
    for i, recipe in enumerate(recipes):
        text = narration_text(recipe)
        lo, hi = speech_window(text)
        raw = work / f"{i:03d}_voice.wav"
        synthesize(text, raw, target_min=lo, target_max=hi)
        mixed = work / f"{i:03d}_mixed.wav"
        mix(raw, mixed)                      # BGM の関門はここ1箇所だけ
        wavs.append(mixed)
        png = work / f"{i:03d}.png"
        render_frame(recipe).save(png)
        frames.append((png, wav_duration_seconds(mixed)))

    audio_list = work / "audio.txt"
    audio_list.write_text(
        "\n".join(f"file '{w.as_posix()}'" for w in wavs) + "\n", encoding="utf-8")
    frame_list = work / "frames.txt"
    lines = []
    for png, dur in frames:
        lines.append(f"file '{png.as_posix()}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{frames[-1][0].as_posix()}'")   # concat は最後を2度書く
    frame_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(frame_list),
        "-f", "concat", "-safe", "0", "-i", str(audio_list),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-g", "60", "-keyint_min", "60",     # 2秒GOP。YouTube ライブの要件
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-shortest", str(out_path),
    ], check=True, capture_output=True, text=True, errors="replace")
    return out_path
```

`wav_duration_seconds` を import に追加: `from scripts.narrate import SECONDS_PER_CHAR, synthesize, wav_duration_seconds`

- [ ] **Step 6: CLI を足して実素材で1本焼く**

```python
def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "work" / "live" / "loop.mp4")
    ap.add_argument("--exclude-category", action="append", default=[])
    args = ap.parse_args()
    recipes = select_recipes(RECIPES_DIR,
                             exclude_categories=frozenset(args.exclude_category))
    print(f"- レシピ {len(recipes)}件")
    path = build(args.out, recipes)
    print(f"✓ {path}")


if __name__ == "__main__":
    main()
```

Run（VOICEVOX が要る。**40分ぶんの合成に時間がかかる**）:
```bash
python scripts/build_live_loop.py --out work/live/loop.mp4
```
Expected: `work/live/loop.mp4` ができ、`ffprobe` で尺が **2,000〜2,900秒**（約33〜48分）に入る。

- [ ] **Step 7: 実測値を確認する**

Run:
```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 work/live/loop.mp4
```
Expected: 上記の窓に入る。**外れたら止めて報告する**（設計の「1周およそ40分」が崩れる）。

- [ ] **Step 8: コミット**

```bash
git add scripts/build_live_loop.py tests/test_build_live_loop.py
git commit -m "ライブ配信: loop.mp4 のビルドを追加（audio_mix を通す）"
```

---

### Task 6: ローテーション判定と12時間の関門

**Files:**
- Create: `scripts/run_live.py`
- Test: `tests/test_run_live.py`

**Interfaces:**
- Consumes: なし（純関数）
- Produces: `ROTATE_AFTER: timedelta`、`HARD_LIMIT: timedelta`、`should_rotate(started_at: datetime, now: datetime) -> bool`、`ArchiveWindowExceeded(RuntimeError)`、`assert_within_archive_window(started_at: datetime, now: datetime) -> None`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/test_run_live.py
from datetime import datetime, timedelta

import pytest

from scripts.run_live import (HARD_LIMIT, ROTATE_AFTER, ArchiveWindowExceeded,
                              assert_within_archive_window, should_rotate)

T0 = datetime(2026, 9, 9, 0, 0, 0)


def test_11時間半で切り替える():
    assert not should_rotate(T0, T0 + timedelta(hours=11, minutes=29))
    assert should_rotate(T0, T0 + timedelta(hours=11, minutes=31))


def test_切り替えの閾値は12時間より手前():
    """12時間を超えるとアーカイブが作られず、その配信の再生時間は
    1分も4,000時間に入らない。マージンが無いと一度の遅延で全部失う。"""
    assert ROTATE_AFTER < HARD_LIMIT
    assert HARD_LIMIT <= timedelta(hours=12)
    assert HARD_LIMIT - ROTATE_AFTER >= timedelta(minutes=20)


def test_12時間に達したら例外で止まる():
    assert_within_archive_window(T0, T0 + timedelta(hours=11, minutes=59))
    with pytest.raises(ArchiveWindowExceeded):
        assert_within_archive_window(T0, T0 + timedelta(hours=12))
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.run_live'`

- [ ] **Step 3: 最小の実装を書く**

```python
#!/usr/bin/env python3
"""24時間のライブ配信を回す。ffmpeg は止めず、配信枠だけを差し替える。

  python scripts/run_live.py
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "live.json"

# アーカイブは12時間未満の配信でしか作られない（YouTube公式ヘルプ）。
# 超えた瞬間、その配信の再生時間は1分も4,000時間に入らない。
HARD_LIMIT = timedelta(hours=12)
# 30分のマージン。API の一時的な失敗で1回分を丸ごと失わないため。
ROTATE_AFTER = timedelta(hours=11, minutes=30)


class ArchiveWindowExceeded(RuntimeError):
    """12時間に達した。この配信のアーカイブはもう作られない。"""


def should_rotate(started_at: datetime, now: datetime) -> bool:
    return now - started_at >= ROTATE_AFTER


def assert_within_archive_window(started_at: datetime, now: datetime) -> None:
    if now - started_at >= HARD_LIMIT:
        raise ArchiveWindowExceeded(
            f"配信開始から {now - started_at} 経過。アーカイブが作られません。")
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: PASS（3件）

- [ ] **Step 5: コミット**

```bash
git add scripts/run_live.py tests/test_run_live.py
git commit -m "ライブ配信: ローテーション判定と12時間の関門を追加"
```

---

### Task 7: 二重起動ロック（枠を作る関数の中に置く）

**Files:**
- Modify: `scripts/run_live.py`
- Test: `tests/test_run_live.py`

**Interfaces:**
- Consumes: `should_rotate` / `assert_within_archive_window`
- Produces: `AlreadyStreaming(RuntimeError)`、`start_broadcast(youtube, stream_id: str, title: str, *, now: datetime, state_path: Path = STATE) -> str`

`run_live.py` を二重起動すると2本同時配信になる。**ロックはフィルタ側ではなく枠を作る関数の中に置く。** キューのフィルタ側にだけ置いた結果、直接叩く経路が素通りした前例がある（known-issues 2・3・8番、`upload_tiktok.post()`）。

- [ ] **Step 1: 失敗するテストを書く**

```python
import json


class _FakeYouTube:
    """liveBroadcasts.insert / bind / transition の最小の身代わり。"""

    def __init__(self):
        self.calls = []

    def liveBroadcasts(self):
        return self

    def insert(self, **kw):
        self.calls.append(("insert", kw))
        return self

    def bind(self, **kw):
        self.calls.append(("bind", kw))
        return self

    def transition(self, **kw):
        self.calls.append(("transition", kw))
        return self

    def execute(self):
        return {"id": "bc_001"}


def test_枠を作ると状態に書かれる(tmp_path):
    from scripts.run_live import start_broadcast
    state = tmp_path / "live.json"
    got = start_broadcast(_FakeYouTube(), "st_1", "テスト", now=T0, state_path=state)
    assert got == "bc_001"
    assert json.loads(state.read_text(encoding="utf-8"))["broadcast_id"] == "bc_001"


def test_配信中にもう一度呼ぶと止まる(tmp_path):
    """呼び出し側ではなくこの関数の中で止めること。
    直接叩く経路が素通りすると2本同時配信になる。"""
    from scripts.run_live import AlreadyStreaming, start_broadcast
    state = tmp_path / "live.json"
    start_broadcast(_FakeYouTube(), "st_1", "1本目", now=T0, state_path=state)
    with pytest.raises(AlreadyStreaming):
        start_broadcast(_FakeYouTube(), "st_1", "2本目", now=T0, state_path=state)
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: FAIL — `ImportError: cannot import name 'start_broadcast'`

- [ ] **Step 3: 最小の実装を書く**

```python
import json


class AlreadyStreaming(RuntimeError):
    """すでに配信中の枠がある。二重起動すると2本同時配信になる。"""


def _read_state(state_path: Path) -> dict:
    if not Path(state_path).exists():
        return {}
    return json.loads(Path(state_path).read_text(encoding="utf-8"))


def _write_state(state_path: Path, data: dict) -> None:
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def start_broadcast(youtube, stream_id: str, title: str, *,
                    now: datetime, state_path: Path = STATE) -> str:
    """配信枠を1つ作り、ストリームに結び付けて live にする。

    **関門はこの関数の中にある。** 呼び出し側に移さないこと。
    """
    state = _read_state(state_path)
    if state.get("broadcast_id") and state.get("live"):
        raise AlreadyStreaming(
            f"配信中の枠があります: {state['broadcast_id']}"
            f"（開始 {state.get('started_at')}）")

    body = {
        "snippet": {"title": title,
                    "scheduledStartTime": now.isoformat() + "Z"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        # 自動で終わられるとローテーションの制御を失う
        "contentDetails": {"enableAutoStart": False, "enableAutoStop": False},
    }
    broadcast_id = youtube.liveBroadcasts().insert(
        part="snippet,status,contentDetails", body=body).execute()["id"]
    youtube.liveBroadcasts().bind(
        part="id,contentDetails", id=broadcast_id, streamId=stream_id).execute()
    youtube.liveBroadcasts().transition(
        part="id,status", id=broadcast_id, broadcastStatus="live").execute()

    _write_state(state_path, {"broadcast_id": broadcast_id, "stream_id": stream_id,
                              "started_at": now.isoformat(), "live": True})
    return broadcast_id
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: PASS（5件）

- [ ] **Step 5: コミット**

```bash
git add scripts/run_live.py tests/test_run_live.py
git commit -m "ライブ配信: 二重起動ロックを枠を作る関数の中に置く"
```

---

### Task 8: 枠の終了と常駐ループ

**Files:**
- Modify: `scripts/run_live.py`
- Test: `tests/test_run_live.py`

**Interfaces:**
- Consumes: `start_broadcast` / `should_rotate` / `assert_within_archive_window`
- Produces: `complete_broadcast(youtube, *, state_path: Path = STATE) -> str | None`、`ensure_stream(youtube) -> tuple[str, str]`（stream_id と RTMP のキー）、`main() -> None`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_枠を終了すると状態のliveが下りる(tmp_path):
    from scripts.run_live import complete_broadcast, start_broadcast
    state = tmp_path / "live.json"
    yt = _FakeYouTube()
    start_broadcast(yt, "st_1", "1本目", now=T0, state_path=state)
    got = complete_broadcast(yt, state_path=state)
    assert got == "bc_001"
    assert json.loads(state.read_text(encoding="utf-8"))["live"] is False


def test_終了したあとなら次の枠を作れる(tmp_path):
    from scripts.run_live import complete_broadcast, start_broadcast
    state = tmp_path / "live.json"
    yt = _FakeYouTube()
    start_broadcast(yt, "st_1", "1本目", now=T0, state_path=state)
    complete_broadcast(yt, state_path=state)
    start_broadcast(yt, "st_1", "2本目", now=T0, state_path=state)   # 例外が出ないこと


def test_配信中の枠が無ければ終了は何もしない(tmp_path):
    from scripts.run_live import complete_broadcast
    assert complete_broadcast(_FakeYouTube(), state_path=tmp_path / "live.json") is None
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: FAIL — `ImportError: cannot import name 'complete_broadcast'`

- [ ] **Step 3: 最小の実装を書く**

```python
def complete_broadcast(youtube, *, state_path: Path = STATE) -> str | None:
    """配信中の枠を終了してアーカイブを確定させる。無ければ None。"""
    state = _read_state(state_path)
    broadcast_id = state.get("broadcast_id")
    if not broadcast_id or not state.get("live"):
        return None
    youtube.liveBroadcasts().transition(
        part="id,status", id=broadcast_id, broadcastStatus="complete").execute()
    state["live"] = False
    _write_state(state_path, state)
    return broadcast_id
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: PASS（8件）

- [ ] **Step 5: 再利用ストリームの確保と常駐ループを書く**

```python
import subprocess
import time

from scripts.upload_youtube import get_service

RTMP_BASE = "rtmp://a.rtmp.youtube.com/live2"
LOOP_MP4 = ROOT / "work" / "live" / "loop.mp4"


def ensure_stream(youtube) -> tuple[str, str]:
    """再利用可能なストリームを1本用意し、(stream_id, ストリームキー) を返す。

    キーは固定。ffmpeg はこのキーに向けて流し続け、枠だけが差し替わる。
    """
    existing = youtube.liveStreams().list(
        part="id,cdn", mine=True, maxResults=50).execute().get("items", [])
    for item in existing:
        if item["cdn"].get("ingestionType") == "rtmp":
            return item["id"], item["cdn"]["ingestionInfo"]["streamName"]
    created = youtube.liveStreams().insert(part="snippet,cdn", body={
        "snippet": {"title": "news-radio"},
        "cdn": {"frameRate": "30fps", "resolution": "1080p",
                "ingestionType": "rtmp"},
    }).execute()
    return created["id"], created["cdn"]["ingestionInfo"]["streamName"]


def _spawn_ffmpeg(key: str) -> subprocess.Popen:
    """loop.mp4 を無限ループで RTMP に流す。**再エンコードしない。**"""
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-re", "-stream_loop", "-1", "-fflags", "+genpts",
        "-i", str(LOOP_MP4), "-c", "copy", "-f", "flv", f"{RTMP_BASE}/{key}",
    ])


def main() -> None:
    youtube = get_service()
    stream_id, key = ensure_stream(youtube)
    proc = _spawn_ffmpeg(key)
    started = datetime.utcnow()
    start_broadcast(youtube, stream_id,
                    f"ニュースラジオ {started:%Y-%m-%d %H:%M} UTC", now=started)
    try:
        while True:
            time.sleep(60)
            now = datetime.utcnow()
            if proc.poll() is not None:                 # ffmpeg が落ちた
                proc = _spawn_ffmpeg(key)
            # 枠を切り替えられないまま12時間に達したら、配信ごと止める。
            # 続けてアーカイブを丸ごと失うより、止めて11時間分を確定させる方が得。
            assert_within_archive_window(started, now)
            if should_rotate(started, now):
                complete_broadcast(youtube)
                started = datetime.utcnow()
                start_broadcast(youtube, stream_id,
                                f"ニュースラジオ {started:%Y-%m-%d %H:%M} UTC",
                                now=started)
    except (KeyboardInterrupt, ArchiveWindowExceeded) as e:
        print(f"! 配信を止めます: {e}")
    finally:
        proc.terminate()
        complete_broadcast(youtube)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 全テストを走らせる**

Run: `python -m pytest -q`
Expected: 既存601件 + 新規16件が PASS。**既存の601件が1件も落ちないこと。**

- [ ] **Step 7: コミット**

```bash
git add scripts/run_live.py tests/test_run_live.py
git commit -m "ライブ配信: 枠の終了と24時間の常駐ループを追加"
```

---

### Task 9: 実配信で通す（未検証の3点を潰す）

**Files:** なし（設計書の「未確認」節を更新する）

> ⚠ **公開配信。実行前にオーナーの承認を取ること。**

- [ ] **Step 1: 短く回して枠の差し替えを確認する**

`ROTATE_AFTER` を一時的に `timedelta(minutes=3)` にして `python scripts/run_live.py` を10分ほど走らせる。
Expected: 枠が3本作られ、**ffmpeg を再起動せずに** 2本目・3本目が live になる。ならなければ設計書のとおり「11.5時間ごとに ffmpeg も再起動する」形に落とす。

- [ ] **Step 2: ループ境界を確認する**

`loop.mp4` の尺より長く流し、ループのつなぎ目で映像・音声が飛ばないことを YouTube の視聴画面で見る。
Expected: 飛ばない。飛ぶなら `-fflags +genpts` の効果が無いということなので、`-c copy` をやめて再エンコードに落とす（CPU が上がる。設計書に記録する）。

- [ ] **Step 3: `ROTATE_AFTER` を戻す**

`timedelta(hours=11, minutes=30)` に戻し、`python -m pytest tests/test_run_live.py -v` が通ることを確認する。

- [ ] **Step 4: 結果を設計書に書いてコミット**

```bash
git add docs/superpowers/specs/2026-09-09-live-streaming-design.md scripts/run_live.py
git commit -m "ライブ配信: 実配信で枠の差し替えとループ境界を確認した"
```

---

## Self-Review

**1. Spec coverage**

| 仕様 | タスク |
|---|---|
| 入力は `recipes/*.json` だけ | Task 2 |
| カテゴリ除外（公職選挙法129条） | Task 2 |
| 読み上げは見出し・逐語引用・出典だけ | Task 3 |
| 写真を使わない | Task 4 |
| `audio_mix.mix()` を通す（関門を新設しない） | Task 5 |
| `-c copy` で再エンコードしない | Task 5（2秒GOP）/ Task 8 |
| 毎日 `loop.mp4` を作り直す | **未カバー → 下記に追記** |
| 11.5時間ローテーション / 12時間の関門 | Task 6 |
| 二重起動ロックを枠を作る関数の中に | Task 7 |
| 失敗時は「アーカイブ > 配信の継続」 | Task 8（`assert_within_archive_window` で止める） |
| アーカイブが計上されるかの実測 | Task 1 |
| 未検証3点（bind / ループ境界 / 有効化） | Task 9 |
| `mix()` が40分で通るか | Task 5 Step 6-7 |

**2. Placeholder scan:** TBD / TODO / 「適切に」なし。全コード実体あり。

**3. Type consistency:** `state_path` は全関数で `Path`。`start_broadcast` / `complete_broadcast` は同じ state 形式（`broadcast_id` / `stream_id` / `started_at` / `live`）を読み書きする。`should_rotate` と `assert_within_archive_window` はどちらも `(datetime, datetime)`。

---

### Task 10: `loop.mp4` の日次差し替え（Self-Review で見つかった漏れ）

**Files:**
- Modify: `scripts/run_live.py`
- Test: `tests/test_run_live.py`

**Interfaces:**
- Consumes: `should_rotate`
- Produces: `should_rebuild(last_built: datetime | None, now: datetime) -> bool`

設計書は「1日2回のローテーションのうち朝の回でだけ ffmpeg を止めて `loop.mp4` を入れ替える」としている。この判定が Task 6〜8 に無い。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_日付が変わっていれば作り直す():
    from scripts.run_live import should_rebuild
    assert should_rebuild(datetime(2026, 9, 8, 23, 0), datetime(2026, 9, 9, 6, 0))


def test_同じ日なら作り直さない():
    from scripts.run_live import should_rebuild
    assert not should_rebuild(datetime(2026, 9, 9, 0, 0), datetime(2026, 9, 9, 23, 0))


def test_一度も作っていなければ作る():
    from scripts.run_live import should_rebuild
    assert should_rebuild(None, datetime(2026, 9, 9, 6, 0))
```

- [ ] **Step 2: 落ちることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: FAIL — `ImportError: cannot import name 'should_rebuild'`

- [ ] **Step 3: 最小の実装を書く**

```python
def should_rebuild(last_built: datetime | None, now: datetime) -> bool:
    """loop.mp4 を作り直すか。1日1回だけ。

    新しい loop.mp4 は ffmpeg を再起動しないと反映されないので、
    ローテーションのうち日付が変わって最初の1回だけで入れ替える。
    """
    if last_built is None:
        return True
    return last_built.date() < now.date()
```

- [ ] **Step 4: 通ることを確認する**

Run: `python -m pytest tests/test_run_live.py -v`
Expected: PASS（11件）

- [ ] **Step 5: 常駐ループに組み込む**

`main()` のローテーション部分を差し替える:

```python
            if should_rotate(started, now):
                complete_broadcast(youtube)
                if should_rebuild(last_built, now):
                    proc.terminate(); proc.wait(timeout=30)
                    from scripts.build_live_loop import (RECIPES_DIR, build,
                                                         select_recipes)
                    build(LOOP_MP4, select_recipes(RECIPES_DIR))
                    last_built = now
                    proc = _spawn_ffmpeg(key)
                started = datetime.utcnow()
                start_broadcast(youtube, stream_id,
                                f"ニュースラジオ {started:%Y-%m-%d %H:%M} UTC",
                                now=started)
```

`main()` の冒頭に `last_built = datetime.utcnow()` を足す（起動時の `loop.mp4` は既存のものを使う）。

- [ ] **Step 6: 全テストを走らせる**

Run: `python -m pytest -q`
Expected: 既存601件 + 新規19件が PASS。

- [ ] **Step 7: コミット**

```bash
git add scripts/run_live.py tests/test_run_live.py
git commit -m "ライブ配信: loop.mp4 の日次差し替えを追加"
```
