"""チャンネルが止まっていないかを外から見る監視のテスト。

RSSは実際には取りに行かない（相手の状態でテスト結果が変わるため）。
解析と日数判定だけを固定のXMLで検証する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import watch_channel
from scripts.watch_channel import Entry, count_recent, latest, parse_entries

JST = timezone(timedelta(hours=9))

# 実際の feed から必要な要素だけを抜いたもの。名前空間は本物と同じ。
FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>日本の最新ニュースまるわかり</title>
  <entry>
    <title>永住許可の手数料20万円は高いのか</title>
    <published>2026-08-12T22:30:16+00:00</published>
  </entry>
  <entry>
    <title>片山大臣が語ったG7の食料品税率</title>
    <published>2026-08-12T10:00:30+00:00</published>
  </entry>
  <entry>
    <title>野田代表が議員定数削減で発言</title>
    <published>2025-12-11T11:01:32+00:00</published>
  </entry>
</feed>
"""


def test_公開日時とタイトルを取り出す():
    got = parse_entries(FEED)
    assert len(got) == 3
    assert got[0].title == "永住許可の手数料20万円は高いのか"
    assert got[0].published == datetime(2026, 8, 12, 22, 30, 16, tzinfo=timezone.utc)


def test_タイムゾーン付きで返す():
    # naive で返すと、JSTの「今」と比較した瞬間に TypeError になる。
    for e in parse_entries(FEED):
        assert e.published.tzinfo is not None


def test_公開日時が無いentryは飛ばす():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>日時なし</title></entry>
  <entry><title>あり</title><published>2026-08-12T22:30:16+00:00</published></entry>
</feed>
"""
    got = parse_entries(xml)
    assert [e.title for e in got] == ["あり"]


def test_直近N日の本数を数える():
    entries = parse_entries(FEED)
    now = datetime(2026, 8, 13, 21, 0, tzinfo=JST)
    # 8/13 21:00 から7日さかのぼると 8/6。8/12 の2本だけが入る
    assert count_recent(entries, now, within_days=7) == 2


def test_閾値の外なら0本になる():
    entries = parse_entries(FEED)
    # 最後の公開から8か月後
    now = datetime(2026, 8, 13, 21, 0, tzinfo=JST) + timedelta(days=365)
    assert count_recent(entries, now, within_days=7) == 0


def test_境界は含める():
    # ちょうど7日前の公開を「止まっている」と判定しない。
    published = datetime(2026, 8, 6, 21, 0, tzinfo=JST)
    entries = [Entry(published=published, title="ちょうど7日前")]
    now = datetime(2026, 8, 13, 21, 0, tzinfo=JST)
    assert count_recent(entries, now, within_days=7) == 1


def test_最後の公開を返す():
    got = latest(parse_entries(FEED))
    assert got is not None
    assert got.title == "永住許可の手数料20万円は高いのか"


def test_1本も無ければ最後の公開は無い():
    assert latest([]) is None


def test_1本でもあれば正常終了する(monkeypatch, capsys):
    monkeypatch.setattr(watch_channel, "fetch_feed", lambda channel_id=None: FEED)
    monkeypatch.setattr(watch_channel, "now_jst",
                        lambda: datetime(2026, 8, 13, 21, 0, tzinfo=JST))
    monkeypatch.setattr("sys.argv", ["watch_channel.py"])

    watch_channel.main()          # SystemExit が飛ばないこと

    out = capsys.readouterr().out
    assert "2本" in out


def test_0本なら終了コード1で落ちる(monkeypatch, capsys):
    # 「止まっている」ことに気づけないと8か月放置の再現になる。
    monkeypatch.setattr(watch_channel, "fetch_feed", lambda channel_id=None: FEED)
    monkeypatch.setattr(watch_channel, "now_jst",
                        lambda: datetime(2027, 8, 13, 21, 0, tzinfo=JST))
    monkeypatch.setattr("sys.argv", ["watch_channel.py"])

    with pytest.raises(SystemExit) as exc:
        watch_channel.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "公開されていません" in err
    # 最後の公開がいつだったかを必ず出す（原因の当たりを付けるため）
    assert "永住許可" in err


def test_一時的な取得失敗の後に成功すればフィードを返す(monkeypatch):
    # 共有ランナーのIPからの単発リクエストは 429 や DNS の一過性障害を
    # 踏みやすい。1回失敗しただけで「チャンネルが死んでいる」ように見える
    # 誤報を出さないよう、3回まではリトライする。
    class _FakeResponse:
        def __init__(self, data: bytes):
            self._data = data

        def read(self) -> bytes:
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    requests: list = []

    def fake_urlopen(req, timeout=30):
        requests.append(req)
        if len(requests) < 3:
            raise OSError("一時的に失敗しました（テスト用）")
        return _FakeResponse(FEED.encode("utf-8"))

    sleeps: list[float] = []
    monkeypatch.setattr(watch_channel.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(watch_channel.time, "sleep", lambda s: sleeps.append(s))

    got = watch_channel.fetch_feed()

    assert got == FEED
    assert len(requests) == 3
    assert sleeps == [2, 5]              # 1回目失敗後2秒、2回目失敗後5秒
    # 既定の User-Agent（Python-urllib/x.y）はデータセンターIPからの
    # 429 の的になりやすいため、明示的に設定してあること。
    assert requests[0].get_header("User-agent")


def test_取得が持続的に失敗すれば送出する(monkeypatch):
    # 失敗閉じ（fail closed）は維持する。リトライしても駄目なら諦めて
    # 例外を上げ、main() 側が終了コード1で落とせるようにする。
    def always_fail(req, timeout=30):
        raise OSError("接続できません（テスト用）")

    sleeps: list[float] = []
    monkeypatch.setattr(watch_channel.urllib.request, "urlopen", always_fail)
    monkeypatch.setattr(watch_channel.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(OSError):
        watch_channel.fetch_feed()

    assert sleeps == [2, 5]


def test_取得に失敗したときも終了コード1で落ちる(monkeypatch, capsys):
    # 取得できない＝監視できていない。黙って成功にすると、監視が壊れた日から
    # 止まっていることに気づけなくなる。
    def _boom(channel_id=None):
        raise OSError("接続できません")

    monkeypatch.setattr(watch_channel, "fetch_feed", _boom)
    monkeypatch.setattr("sys.argv", ["watch_channel.py"])

    with pytest.raises(SystemExit) as exc:
        watch_channel.main()

    assert exc.value.code == 1
    assert "接続できません" in capsys.readouterr().err


def test_withinが負なら受け付けない(monkeypatch, capsys):
    # --within 0 は「必ず失敗させて通知経路を確認する」ための正規の使い方
    # （watchdog.yml の workflow_dispatch 入力）として意図的に許可するので、
    # 弾くのは負の値だけにする。ap.error() による終了（コード2）であることを
    # 確認し、たまたま0本で終了コード1になっただけではないことを区別する。
    monkeypatch.setattr("sys.argv", ["watch_channel.py", "--within", "-1"])

    with pytest.raises(SystemExit) as exc:
        watch_channel.main()

    assert exc.value.code == 2
    assert "--within" in capsys.readouterr().err


def test_withinが0なら受け付けて必ず終了コード1になる(monkeypatch, capsys):
    # 0を指定すると「直近0日」＝必ず0本になるので、通知経路を手で確かめる
    # ためのレバーとして使える（watchdog.yml のコメント参照）。
    monkeypatch.setattr(watch_channel, "fetch_feed", lambda channel_id=None: FEED)
    monkeypatch.setattr(watch_channel, "now_jst",
                        lambda: datetime(2026, 8, 13, 21, 0, tzinfo=JST))
    monkeypatch.setattr("sys.argv", ["watch_channel.py", "--within", "0"])

    with pytest.raises(SystemExit) as exc:
        watch_channel.main()

    assert exc.value.code == 1
