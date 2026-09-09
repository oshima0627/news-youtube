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
