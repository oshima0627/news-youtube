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
