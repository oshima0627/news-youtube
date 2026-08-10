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
