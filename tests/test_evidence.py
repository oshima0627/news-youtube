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


def test_サブドメイン偽装を拒否する():
    # kokkai.ndl.go.jp を偽った悪意あるサブドメイン（kokkai.ndl.go.jp.evil.com）は不採用
    # endswith(".go.jp") は False になるため、ホスト検証が機能していることを確認
    assert is_admissible(_ev(source_url="https://kokkai.ndl.go.jp.evil.com/x")) is False


def test_パスに紛れ込ませた偽装を拒否する():
    # ホスト部分は example.com だが、パスに kokkai.ndl.go.jp を含ませた悪意あるURL
    # urlparse().hostname は example.com を返すため、.go.jp チェックで不採用になることを確認
    assert is_admissible(_ev(source_url="https://example.com/kokkai.ndl.go.jp/x")) is False


def test_MIN_QUOTE_CHARS_の境界_11文字は不採用():
    # MIN_QUOTE_CHARS = 12 なので、11文字は len(quote.strip()) < MIN_QUOTE_CHARS で不採用
    assert is_admissible(_ev(quote="12345678901", figure="")) is False


def test_MIN_QUOTE_CHARS_の境界_12文字は採用():
    # MIN_QUOTE_CHARS = 12 なので、12文字は len(quote.strip()) >= MIN_QUOTE_CHARS で採用
    assert is_admissible(_ev(quote="123456789012", figure="")) is True


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


def test_フィールドが欠損していてもcontextが壊れない():
    # session / nameOfHouse / nameOfMeeting / date が欠損した応答を想定
    payload = {
        "speechRecord": [
            {
                "speechID": "x",
                "speaker": "野田佳彦",
                "speech": "私どもは議員定数を四十五削減すると申し上げてまいりました。",
                "speechURL": "https://kokkai.ndl.go.jp/#/detail?x=1",
            }
        ]
    }
    got = parse_speeches(payload)

    assert len(got) == 1
    ev = got[0]
    assert "None" not in ev.context
    assert ev.context == "野田佳彦"          # 空要素は詰めて、余分な空白も残さない


def test_speechRecordが単一オブジェクトでもリストとして扱う():
    # 繰り返し要素が1件のとき、配列ではなくオブジェクト単体で返ってくる実装への対策
    payload = {
        "numberOfRecords": 1,
        "speechRecord": {
            "speechID": "121705261X00120251120_001",
            "session": 217,
            "nameOfHouse": "衆議院",
            "nameOfMeeting": "予算委員会",
            "date": "2025-11-20",
            "speaker": "野田佳彦",
            "speakerGroup": "立憲民主党",
            "speech": "私どもは議員定数を四十五削減すると申し上げてまいりました。",
            "speechURL": "https://kokkai.ndl.go.jp/#/detail?minId=121705261X00120251120&spkNum=1",
        },
    }
    got = parse_speeches(payload)

    assert len(got) == 1
    assert got[0].quote == "私どもは議員定数を四十五削減すると申し上げてまいりました。"
    assert "予算委員会" in got[0].context


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_search_speechesが正しいパラメータでAPIを呼ぶ(monkeypatch):
    from scripts import evidence as evidence_module

    captured = {}

    def fake_get(url, timeout=None, params=None):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["params"] = params
        return _FakeResponse({"speechRecord": []})

    monkeypatch.setattr(evidence_module.requests, "get", fake_get)

    evidence_module.search_speeches("議員定数", limit=3)

    assert captured["url"] == evidence_module.KOKKAI_ENDPOINT
    assert captured["params"]["any"] == "議員定数"
    assert captured["params"]["recordPacking"] == "json"
    assert captured["params"]["maximumRecords"] == 3


def test_search_speechesのlimitが100件に丸められる(monkeypatch):
    from scripts import evidence as evidence_module

    captured = {}

    def fake_get(url, timeout=None, params=None):
        captured["params"] = params
        return _FakeResponse({"speechRecord": []})

    monkeypatch.setattr(evidence_module.requests, "get", fake_get)

    evidence_module.search_speeches("議員定数", limit=500)

    assert captured["params"]["maximumRecords"] == 100


def test_search_speechesがEvidenceのリストを返す(monkeypatch):
    from scripts import evidence as evidence_module

    payload = json.loads((FIXTURES / "kokkai_speech.json").read_text(encoding="utf-8"))

    def fake_get(url, timeout=None, params=None):
        return _FakeResponse(payload)

    monkeypatch.setattr(evidence_module.requests, "get", fake_get)

    got = evidence_module.search_speeches("議員定数", limit=3)

    assert len(got) == 1
    assert isinstance(got[0], Evidence)
    assert got[0].quote == "私どもは議員定数を四十五削減すると申し上げてまいりました。"


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
