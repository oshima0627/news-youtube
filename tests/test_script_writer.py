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
