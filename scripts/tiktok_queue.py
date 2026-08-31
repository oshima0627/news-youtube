#!/usr/bin/env python3
"""TikTok 投稿キューの読み書き。

TikTok の Direct Post API には予約投稿のフィールドが無く、投稿した瞬間に出る。
一方この運用は `--days-ahead 3〜5` で先に作り置きするので、「作る時刻」と
「出す時刻」を分ける必要がある。作る側（run_daily.py）はここに積むだけ、
出す側（post_tiktok_due.py）は枠の時刻を過ぎたものを取り出す。

`state/published.json` には触らない。あれは YouTube の重複投稿・二重予約の
防止だけを担っていて、壊れたときの被害範囲を広げたくない。

  state/tiktok_queue.json   投稿待ち [{workdir, due}]
  state/tiktok_posted.json  投稿済み {workdir: {publish_id, ...}}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

QUEUE_NAME = "tiktok_queue.json"
POSTED_NAME = "tiktok_posted.json"


def _read(path: Path, empty):
    if not path.exists():
        return empty
    # BOM 付きで書かれた場合に備えて utf-8-sig（published.json と同じ扱い）
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _key(workdir) -> str:
    """workdir を記録のキーに正規化する。

    Windows では `Path("work/a/tiktok")` を `str()` するとバックスラッシュに
    なる。CLI に `work/a/tiktok` と打っても記録は `work\a\tiktok` で入るので、
    素の文字列比較だと同じ場所を別物として扱い、**重複防止が効かずに同じ動画が
    2本 TikTok に並ぶ**。区切り文字をスラッシュに寄せて1つに決める
    （2026-08-31 の初投稿が実際にバックスラッシュで記録された）。
    """
    return Path(workdir).as_posix()


def load_queue(state_dir: Path) -> list[dict]:
    return _read(Path(state_dir) / QUEUE_NAME, [])


def save_queue(state_dir: Path, entries: list[dict]) -> None:
    _write(Path(state_dir) / QUEUE_NAME, entries)


def load_posted(state_dir: Path) -> dict:
    """投稿済みの記録。**キーは読むときにも正規化する。**

    正規化を入れる前に書かれた記録（バックスラッシュ）が残っているので、
    書くときだけ揃えると古い記録が引けなくなり、投稿済みの動画をもう一度
    投稿してしまう。
    """
    return {_key(k): v for k, v in _read(Path(state_dir) / POSTED_NAME, {}).items()}


def enqueue(state_dir: Path, workdir: str, due: datetime) -> None:
    """投稿待ちに1件積む。

    同じ workdir を二重に積まない。積むと同じ動画が2本 TikTok に並ぶ。
    投稿済みのものも積み直さない（run_daily を同じ題材で2回まわしたとき）。
    """
    workdir = _key(workdir)
    if workdir in load_posted(state_dir):
        return
    entries = load_queue(state_dir)
    if any(_key(e.get("workdir", "")) == workdir for e in entries):
        return
    entries.append({"workdir": workdir, "due": due.isoformat()})
    save_queue(state_dir, entries)


def due_entries(state_dir: Path, now: datetime) -> list[dict]:
    """枠の時刻を過ぎた未投稿を、早い順に返す。

    `due` をパースできない記録は**その1件だけ**飛ばす。落とすと、壊れた1件で
    その日の投稿が全部止まる（unpublish.py / run_daily.py の同じ判断に合わせ、
    黙って飛ばさず必ず警告を出す）。
    """
    posted = load_posted(state_dir)
    ready = []
    for entry in load_queue(state_dir):
        if _key(entry.get("workdir", "")) in posted:
            continue
        try:
            due = datetime.fromisoformat(entry["due"])
        except (KeyError, TypeError, ValueError):
            print(f"! due をパースできません（この1件を飛ばします）: {entry!r}")
            continue
        if due <= now:
            ready.append((due, entry))
    return [entry for _, entry in sorted(ready, key=lambda pair: pair[0])]


def mark_posted(state_dir: Path, workdir: str, result: dict) -> None:
    """投稿済みとして記録し、キューから外す。

    記録するのは **投稿の完了を確認できてから**（post/publish/status/fetch/ が
    PUBLISH_COMPLETE を返してから）。init の 200 だけで記録すると、失敗した
    投稿が「済み」になって二度と出せなくなる。
    """
    workdir = _key(workdir)
    posted = load_posted(Path(state_dir))
    posted[workdir] = result
    _write(Path(state_dir) / POSTED_NAME, posted)
    save_queue(state_dir, [e for e in load_queue(state_dir)
                           if _key(e.get("workdir", "")) != workdir])
