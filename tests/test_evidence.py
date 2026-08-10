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
