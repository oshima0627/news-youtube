import pytest

from scripts.evidence import (
    QUOTE_EXCERPT_MAX_CHARS,
    Evidence,
    EvidenceSourcesUnavailable,
    collect,
    ground_excerpt,
    is_admissible,
)


def _ev(**kw) -> Evidence:
    base = dict(kind="speech", source_url="https://kokkai.ndl.go.jp/#/detail?x=1",
                figure="", quote="議員定数を45削減すると申し上げた",
                context="第217回国会 予算委員会 2025-11-20")
    base.update(kw)
    return Evidence(**base)


QUOTE = "我が国の在留外国人数は、令和七年末時点で過去最多の約四百十三万人となっております。"


def test_逐語引用の部分文字列ならそのまま通す():
    assert ground_excerpt("過去最多の約四百十三万人", QUOTE) == "過去最多の約四百十三万人"


def test_一次資料に無い文言は逐語引用の先頭に差し替える():
    # 画面のカードには一次資料の出典（会議名・日付・発言者）が必ず印字される。
    # モデルが作った文字列にその出典が付くと、「一次資料が取れなければ
    # 公開しない」という設計方針がそこだけ破れる。
    assert ground_excerpt("在留外国人は増え続けている", QUOTE) \
        == QUOTE[:QUOTE_EXCERPT_MAX_CHARS]


def test_空の文言も差し替える():
    assert ground_excerpt("", QUOTE) == QUOTE[:QUOTE_EXCERPT_MAX_CHARS]


def test_前後の空白は落として判定する():
    assert ground_excerpt("  過去最多の約四百十三万人  ", QUOTE) \
        == "過去最多の約四百十三万人"


def test_逐語引用が無ければ差し替えようがないので空を返す():
    # 数値系統（figure）のときはこの関数を通さないが、呼ばれたときに
    # 一次資料に無い文字列をそのまま通すことだけは避ける。
    assert ground_excerpt("なんらかの文言", "") == ""


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


def test_単位を伴わない数字だけの図表値は認めない():
    # 数字が1文字でもあれば通す判定だと、統計表ID・ページ番号のように
    # 「数量ではないが数字を含む文字列」が採用ゲートを通ってしまう
    # （Task 4 で e-Stat 系統をまるごと外す原因になった穴）
    assert is_admissible(_ev(quote="", figure="p2")) is False
    assert is_admissible(_ev(quote="", figure="0003412345")) is False
    assert is_admissible(_ev(quote="", figure="表 12")) is False


def test_調査年度は数値として認めない():
    # 統計表メタデータの調査年度が「具体的な数値」として通ると、
    # 上と同じ穴が開く
    assert is_admissible(_ev(quote="", figure="2024年度")) is False


def test_単位を伴う数量は認める():
    for figure in ("45議席", "1,234人", "3.5%", "12兆円", "30％減", "５件"):
        assert is_admissible(_ev(quote="", figure=figure)) is True, figure


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


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """リトライのバックオフでテストを待たせない。"""
    from scripts import evidence as evidence_module
    monkeypatch.setattr(evidence_module.time, "sleep", lambda s: None)


def test_search_speechesは一過性の失敗をリトライして成功を返す(monkeypatch):
    # 系統が国会会議録の1つしか無いため、1回の 5xx がそのまま
    # 「全系統ダウン」として run_daily の中止判断まで届いてしまう。
    # 送出する前にここで粘る（I2）。
    from scripts import evidence as evidence_module

    payload = json.loads((FIXTURES / "kokkai_speech.json").read_text(encoding="utf-8"))
    attempts = []

    def flaky_get(url, timeout=None, params=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("503 Server Error")
        return _FakeResponse(payload)

    monkeypatch.setattr(evidence_module.requests, "get", flaky_get)

    got = evidence_module.search_speeches("議員定数", limit=3)

    assert len(attempts) == 3
    assert len(got) == 1


def test_search_speechesはリトライを使い切ったら最後の例外を送出する(monkeypatch):
    from scripts import evidence as evidence_module

    attempts = []

    def always_fail(url, timeout=None, params=None):
        attempts.append(1)
        raise RuntimeError("504 Gateway Timeout")

    monkeypatch.setattr(evidence_module.requests, "get", always_fail)

    with pytest.raises(RuntimeError, match="504"):
        evidence_module.search_speeches("議員定数")

    assert len(attempts) == evidence_module.RETRY_ATTEMPTS


def test_search_speechesは成功したらリトライしない(monkeypatch):
    from scripts import evidence as evidence_module

    attempts = []

    def ok_get(url, timeout=None, params=None):
        attempts.append(1)
        return _FakeResponse({"speechRecord": []})

    monkeypatch.setattr(evidence_module.requests, "get", ok_get)
    evidence_module.search_speeches("議員定数")

    assert len(attempts) == 1


def test_build_recipeは候補と根拠から再現可能なレシピを作る():
    # run_daily.py と verify_source.py が同じ形のレシピを別々に組み立てて
    # いると、片方だけ形が変わったときに再現できないレシピが混ざる
    from scripts.evidence import build_recipe

    ev = _ev()
    got = build_recipe(
        {"id": "abc", "title": "見出し", "keyword": "議員定数", "category": "政治"}, ev)

    assert got == {
        "id": "abc",
        "headline": "見出し",
        "keyword": "議員定数",
        "category": "政治",
        "evidence": {
            "kind": ev.kind,
            "source_url": ev.source_url,
            "figure": ev.figure,
            "quote": ev.quote,
            "context": ev.context,
            "speaker": ev.speaker,
        },
    }


def test_run_dailyとverify_sourceは同じbuild_recipeを使う():
    from scripts import evidence, run_daily, verify_source

    assert run_daily.build_recipe is evidence.build_recipe
    assert verify_source.build_recipe is evidence.build_recipe


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


def test_collectは検索語が近接して現れる箇所だけを引用にする(monkeypatch):
    # collect() は発言全文をそのまま引用にしない。国会の発言は1件2,000字を
    # 超えるので、全文を渡すと後段（台本生成）が題材と無関係な部分を抜き出せて
    # しまう。検索語が固まって現れる箇所だけに絞る。
    speech = ("○委員長　次に、別の議題に移ります。" + "冒頭の無関係な前置きです。" * 20
              + "飲食料品の消費税率を一％にした場合の減税額についてお答えします。"
              + "その後の無関係な結びです。" * 20)
    whole = Evidence(kind="speech", source_url="https://kokkai.ndl.go.jp/#/x",
                     figure="", quote=speech, context="予算委員会")

    monkeypatch.setattr("scripts.evidence.search_speeches",
                        lambda k, limit=20: [whole])

    got = collect("消費 減税")

    assert len(got) == 1
    assert "消費税率を一％にした場合の減税額" in got[0].quote
    assert "冒頭の無関係な前置き" not in got[0].quote
    assert len(got[0].quote) < len(speech)
    # 引用以外（出典・文脈）はそのまま引き継ぐ
    assert got[0].source_url == whole.source_url
    assert got[0].context == whole.context


def test_collectは検索語が散らばっているだけの発言を落とす(monkeypatch):
    # これが無いと採用ゲートが機能しない。長い発言なら「消費」も「減税」も
    # どこかには出てくるので、「語が発言のどこかにある」を条件にすると
    # 消費税減税の見出しに憲法審査会の答弁が付く（実測でそうなった）。
    scattered = Evidence(
        kind="speech", source_url="https://kokkai.ndl.go.jp/#/x", figure="",
        quote=("消費生活センターの体制についてお尋ねします。" + "別の話題が続きます。" * 40
               + "次に、災害減税措置の期限について伺います。"),
        context="予算委員会")

    monkeypatch.setattr("scripts.evidence.search_speeches",
                        lambda k, limit=20: [scattered])

    assert collect("消費 減税") == []


def test_collectは検索語が1語しかなければ一次資料に当てに行かない(monkeypatch):
    # 1語では近接判定が成立せず、「その語がどこかに出てくる発言」しか
    # 区別できない。関連性を確かめられない題材は最初から採らない。
    def boom(*a, **kw):
        raise AssertionError("1語の検索語で search_speeches を呼んでいる")

    monkeypatch.setattr("scripts.evidence.search_speeches", boom)

    assert collect("議員定数") == []


def test_collectは関連性の高い順に並べて返す(monkeypatch):
    # 呼び出し側（run_daily / verify_source）は found[0] だけを使うので、
    # 並び順がそのまま採用される根拠を決める。
    weak = Evidence(kind="speech", source_url="https://kokkai.ndl.go.jp/#/weak",
                    figure="",
                    quote="消費税の減税につきましては、党内で引き続き検討してまいります。",
                    context="予算委員会")
    strong = Evidence(kind="speech", source_url="https://kokkai.ndl.go.jp/#/strong",
                      figure="",
                      quote="飲食料品の消費税を一％に下げる減税の減収額は四・三兆円になります。",
                      context="予算委員会")

    monkeypatch.setattr("scripts.evidence.search_speeches",
                        lambda k, limit=20: [weak, strong])

    got = collect("消費 減税")

    assert [e.source_url for e in got] == [strong.source_url, weak.source_url]


def test_collectは取得に成功したが採用条件を満たすものが無ければ空リストを返す(monkeypatch):
    # 環境（API疎通）は正常で、単に該当する発言が無かった／採用ゲートを通らな
    # かっただけのケース。この場合は例外にせず、従来どおり空リストを返す
    # （EvidenceSourcesUnavailable と明確に区別する）。
    not_admissible = Evidence(kind="speech", source_url="https://kokkai.ndl.go.jp/#/x",
                              figure="", quote="議員定数。", context="予算委員会")

    monkeypatch.setattr("scripts.evidence.search_speeches",
                        lambda k, limit=20: [not_admissible])

    assert collect("議員 定数") == []


# --- 関連性の判定（find_passage） ------------------------------------------

def test_find_passageは検索語を含む文だけを切り出す():
    from scripts import evidence as evidence_module
    # 前後の無関係な文を引きずり込まない。ここが緩いと、引用カードに
    # 出る文字列と題材が食い違う。
    speech = ("○委員長　次に、別の議題に移ります。"
              + "冒頭の無関係な前置きです。" * 20
              + "飲食料品の消費税率を一％にした場合の減税額についてお答えします。"
              + "その後の無関係な結びです。" * 20)

    got = evidence_module.find_passage(speech, ["消費", "減税"])

    assert got is not None
    assert got[0] == "飲食料品の消費税率を一％にした場合の減税額についてお答えします。"


def test_find_passageは語が離れていれば切り出さない():
    from scripts import evidence as evidence_module
    # 長い発言なら「消費」も「減税」もどこかには出てくる。離れていても
    # 通してしまうと、採用ゲートが実質「語がある」だけになる。
    speech = ("消費生活センターの体制についてお尋ねします。"
              + "全く別の話題が続きます。" * 40
              + "次に、災害減税措置の期限について伺います。")

    assert evidence_module.find_passage(speech, ["消費", "減税"]) is None


def test_find_passageは検索語が1種類しか無ければ切り出さない():
    from scripts import evidence as evidence_module

    speech = "消費税について申し上げます。" * 10

    assert evidence_module.find_passage(speech, ["消費", "減税"]) is None


def test_find_passageは根拠になった検索語を引用から落とさない():
    # 引用の末尾を句点で閉じるとき、最後の検索語より手前で閉じてしまうと、
    # 「その箇所を根拠として採用した理由」そのものが引用から消える。
    # 画面の引用カードには一次資料の出典キャプションが必ず付くので、
    # 根拠の見えない文に出典だけが付いた状態になってしまう。
    from scripts import evidence as evidence_module

    # 検索語より手前で閉じた場合でも引用が短くなりすぎない（＝窓ごと使う
    # 救済措置が働かない）長さにしてある。救済措置に隠れると、この欠陥が
    # 起きていることをテストで検出できない。
    speech = ("冒頭の無関係な文です。"
              "消費税の在り方につきましては、これまで長きにわたり与野党で"
              "議論を重ねてきたところでございます。"
              "続いて減税の具体的な中身に入ります。")

    got = evidence_module.find_passage(speech, ["消費", "減税"])

    assert got is not None
    assert "消費" in got[0]
    assert "減税" in got[0]


def test_find_passageは数値を含む箇所を高く評価する():
    from scripts import evidence as evidence_module
    # 同点候補の順位付けにしか使わないが、数値がある箇所のほうが
    # 「データで裏付ける解説」という番組の型に合う。
    plain = "消費税の減税につきましては、党内で引き続き検討してまいります。"
    with_figure = "消費税の減税による減収額は約四・三兆円になると見込んでおります。"

    a = evidence_module.find_passage(plain, ["消費", "減税"])
    b = evidence_module.find_passage(with_figure, ["消費", "減税"])

    assert a is not None and b is not None
    assert b[1] > a[1]


def test_search_speechesは古すぎる発言を除くため期間を指定する(monkeypatch):
    # 国会会議録は1947年から入っている。指定しないと今日のニュースの根拠に
    # 10年前の答弁が返ってくる（会議名と日付は画面にも出るので古いこと自体は
    # 隠れないが、「今の政策の解説」として成立しなくなる）。
    from scripts import evidence as evidence_module

    captured: dict = {}

    def fake_get(url, timeout=None, params=None):
        captured.update(params)
        return _FakeResponse({"speechRecord": []})

    monkeypatch.setattr(evidence_module.requests, "get", fake_get)

    evidence_module.search_speeches("消費 減税")

    assert captured["any"] == "消費 減税"
    assert captured["from"] == evidence_module.since_date()


def test_since_dateは指定年数ぶん遡る():
    from datetime import date

    from scripts import evidence as evidence_module

    got = evidence_module.since_date(date(2026, 8, 12))

    assert got == f"{2026 - evidence_module.SPEECH_SINCE_YEARS:04d}-08-12"
