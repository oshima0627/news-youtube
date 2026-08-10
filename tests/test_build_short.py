from PIL import Image

from scripts.build_short import compose_stage
from scripts.cards import SHORT_SIZE

SCRIPT = {"headline": "中国軍機が照射", "narration": "レーダー照射は攻撃の一歩手前",
          "figure_label": "照射回数", "figure_value": "1回",
          "title": "t", "tags": []}


def test_下地は縦型の不透明画像になる(tmp_path):
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (1600, 900), (80, 90, 110)).save(photo)

    got = compose_stage(photo, SCRIPT, source="国会会議録")
    assert got.size == SHORT_SIZE
    assert got.mode == "RGB"


def test_縦長の写真でも横幅いっぱいに収まる(tmp_path):
    photo = tmp_path / "tall.jpg"
    Image.new("RGB", (600, 1800), (10, 20, 30)).save(photo)

    got = compose_stage(photo, SCRIPT, source="e-Stat")
    assert got.size == SHORT_SIZE
