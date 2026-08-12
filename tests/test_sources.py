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


# --- 題材の門番と検索語 ------------------------------------------------------

MIXED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>食料品消費税減税 政府が基本方針決定</title>
    <link>https://www3.nhk.or.jp/news/html/10.html</link>
  </item>
  <item>
    <title>北日本と東日本中心 9日も大気の状態が非常に不安定</title>
    <link>https://www3.nhk.or.jp/news/html/11.html</link>
  </item>
</channel></rss>
"""


def test_国会で議論されえない題材は候補にしない():
    # 残しても一次資料には当たらないか、当たっても無関係な答弁しか
    # 返ってこない（実測では天気の見出しに令和五年度決算の質疑が付いた）。
    got = rank(parse_feed(MIXED_XML), set())

    assert [c["title"] for c in got] == ["食料品消費税減税 政府が基本方針決定"]


def test_検索語は名詞を空白で区切ったものになる():
    # 国会会議録APIの any は空白区切りのAND検索。見出しをそのまま渡すと
    # 1件も当たらない（実測12件中0件）。
    got = rank(parse_feed(MIXED_XML), set())

    words = got[0]["keyword"].split()
    assert 2 <= len(words) <= 3
    assert all(w in got[0]["title"] for w in words)
    assert got[0]["keyword"] != got[0]["title"]
