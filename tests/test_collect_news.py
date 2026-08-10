"""collect_news.py の「環境不備」の扱いを検証する。

evidence.collect() は「取得元が1系統も応答しない」を EvidenceSourcesUnavailable
として正常系（根拠が無かった）と区別しているのに、入口の RSS 側が全滅を
握りつぶして空の candidates.json を exit 0 で書いていると、その日は
run_daily.py が候補0件のまま「本日 0/2 本」と表示して終了コード0で終わる。
原因に気づけないまま何日も投稿が止まるので、入口も非対称にしない。
"""

from __future__ import annotations

import json

import pytest

from scripts import collect_news


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>総理が国会で中国について答弁</title>
        <link>https://www3.nhk.or.jp/news/html/1.html</link></item>
</channel></rss>
"""


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_news, "OUT", tmp_path / "candidates.json")
    monkeypatch.setattr(collect_news, "SEEN", tmp_path / "seen.json")
    monkeypatch.setattr("sys.argv", ["collect_news.py", "--limit", "20"])


def test_全フィードが失敗したら非0終了する(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)

    def always_fail(url, timeout=None):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(collect_news.requests, "get", always_fail)

    with pytest.raises(SystemExit) as exc_info:
        collect_news.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "すべてのRSSフィード" in err
    assert "Connection refused" in err     # 原因がそのまま出る


def test_一部のフィードが生きていれば従来どおり続行する(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    first = collect_news.FEEDS[0]

    def one_ok(url, timeout=None):
        if url == first:
            return _FakeResponse(FEED_XML)
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(collect_news.requests, "get", one_ok)

    collect_news.main()                    # SystemExit は起きない

    picked = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert len(picked) == 1


def test_候補が0件なら非0終了する(tmp_path, monkeypatch, capsys):
    # 取得自体は全部成功しているが、中身が空（または seen で全部除外された）
    # ケース。空の candidates.json を exit 0 で書くと原因に気づけない。
    _setup(tmp_path, monkeypatch)
    empty = """<?xml version="1.0"?><rss><channel></channel></rss>"""

    monkeypatch.setattr(collect_news.requests, "get",
                        lambda url, timeout=None: _FakeResponse(empty))

    with pytest.raises(SystemExit) as exc_info:
        collect_news.main()

    assert exc_info.value.code == 1
    assert "候補が1件もありません" in capsys.readouterr().err
