"""見出しから検索語を作る処理と、題材の門番のテスト。

背景（実測）: 見出しの先頭40字を国会会議録の全文検索（空白区切りのAND）に
渡すと12件中0件しか当たらなかった。名詞2〜3語にすると12件中12件当たった
が、当たった発言は題材と無関係なものばかりだった。当てやすくするだけでは
足りず、そもそも国会で議論されえない題材を先に落とす必要がある。
"""

from scripts.keywords import MIN_KEYWORDS, extract, is_policy_topic


def test_政策の題材は一次資料に当てに行く():
    assert is_policy_topic("食料品消費税減税 政府が基本方針決定") is True
    assert is_policy_topic("外国人の永住許可 世帯年収を考慮") is True
    assert is_policy_topic("防衛白書「新しい戦い方」に対応") is True


def test_国会で議論されえない題材は落とす():
    # 天気やスポーツの見出しに国会答弁を探しに行けば、無関係な発言しか
    # 返ってこない。実測では「北日本と東日本中心 大気の状態が不安定」に
    # 令和五年度決算の質疑が、「韓国サッカー協会が…」に東京五輪の答弁が
    # 付いた。当てに行く前に落とす。
    assert is_policy_topic("北日本と東日本中心 9日も大気の状態が非常に不安定") is False
    assert is_policy_topic("プロ野球 阪神が3連勝で首位に") is False


def test_固有名詞を先に拾う():
    # 国会会議録の全文検索で題材を絞る力は、一般名詞より固有名詞が強い。
    got = extract("食料品の消費税減税 ねらいは カギを握る片山財務相に聞く")
    assert got[0] == "片山"


def test_元号や年度は検索語にしない():
    # 「令和」は固有名詞なので素通しにすると最優先で拾われるが、題材を
    # 1ミリも絞らない。実測ではこれのせいで年金積立金の見出しに
    # NISA の答弁が付いた。
    got = extract("公的年金積立金 過去最高302兆円余 令和7年度決算")
    assert "令和" not in got
    assert "年金" in got


def test_定型の飾り語は検索語にしない():
    got = extract("【速報】政府が減税の基本方針を発表 今回の対応は")
    for noise in ("速報", "発表", "今回", "対応"):
        assert noise not in got


def test_検索語は多くても3語():
    got = extract("外国人の永住許可 世帯年収が日本人の平均を上回る水準かを考慮")
    assert len(got) <= 3


def test_検索語が2語に満たない見出しがありうる():
    # collect() はこの場合に一次資料へ当てに行かない（近接判定が成立せず、
    # 関連性を確かめられないため）。その分岐が机上の空論でないことを示す。
    assert len(extract("減税へ")) < MIN_KEYWORDS
