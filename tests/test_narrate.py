import pytest

from scripts.narrate import resolve_speaker

SPEAKERS = [
    {"name": "四国めたん", "styles": [{"name": "ノーマル", "id": 2}]},
    {"name": "青山龍星", "styles": [
        {"name": "ノーマル", "id": 13},
        {"name": "熱血", "id": 81},
    ]},
]


def test_名前からノーマルの話者IDを引く():
    assert resolve_speaker(SPEAKERS, "青山龍星") == 13


def test_居ない話者は例外にする():
    # 黙って別の声で作ると、既存視聴者の耳と合わない動画が公開される
    with pytest.raises(ValueError, match="見つかりません"):
        resolve_speaker(SPEAKERS, "存在しない話者")
