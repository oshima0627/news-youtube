import json
from pathlib import Path

from scripts.build_live_loop import narration_text, render_frame, select_recipes
from scripts.cards_wide import WIDE_SIZE

_R = {
    "id": "aaa", "headline": "奨学金の返済が長期化している", "category": "教育",
    "evidence": {"quote": "平均で十五年かけて返済しています。",
                 "context": "第221回国会 衆議院特別委員会 2026-05-08 谷浩一郎",
                 "source_url": "https://kokkai.ndl.go.jp/txt/1/1", "speaker": "谷浩一郎"},
}


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
