#!/usr/bin/env python3
"""実写を写真帯の縦横比に整える（顔が切れる素材の救済）。

`build_short._fill` は帯（1080x740）を覆うように拡大して切り取る。素材に
余白があるうちは自然に収まるが、**もともとタイトに切り抜かれた顔写真**では
頭頂とあごが窓の外に出る。2026-09-02 に古謝玄太の ja.wikipedia 記事画像
（550x733・余白なし）で実際に起きた。

`_fill` 側を「切り取らない」方式に変えると、余白のある素材（玉城デニーの
1280x1707 など）の収まりまで一緒に変わってしまう。**素材が原因の問題は
素材側で直す**ほうが影響範囲が小さいので、ここで帯と同じ縦横比まで
余白を足しておき、`_fill` には切り取る余地が無い画像を渡す。

余白は元画像を拡大してぼかしたもので埋める。単色だと帯の中に額縁が
できたように見えるため。

  python scripts/frame_photo.py work/<id>

元画像は photo_source.jpg として残すので、何度実行しても結果は変わらない。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cards import PHOTO_H, SHORT_SIZE            # noqa: E402

BLUR_RADIUS = 40
# 背景に使う拡大率。1.0 だと前景と同じ絵がそのまま背後に出て境目が消える。
BACKGROUND_ZOOM = 1.6


def frame_to_aspect(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """target と同じ縦横比の画像にする。足りない側をぼかし背景で埋める。

    すでに target 以上に横長なら何もしない（切り取る余地が無いので
    `_fill` はそのまま覆える）。
    """
    tw, th = target
    if img.width / img.height >= tw / th:
        return img.copy()

    out_h = img.height
    out_w = max(1, round(out_h * tw / th))

    scale = max(out_w / img.width, out_h / img.height) * BACKGROUND_ZOOM
    bg = img.resize((max(1, round(img.width * scale)),
                     max(1, round(img.height * scale))), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    bg = bg.crop(((bg.width - out_w) // 2, (bg.height - out_h) // 2,
                  (bg.width - out_w) // 2 + out_w,
                  (bg.height - out_h) // 2 + out_h))

    bg.paste(img, ((out_w - img.width) // 2, 0))
    return bg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workdir", help="work/<id>")
    a = ap.parse_args()

    workdir = Path(a.workdir)
    photo, source = workdir / "photo.jpg", workdir / "photo_source.jpg"
    if not source.exists():
        if not photo.exists():
            sys.exit(f"✗ {photo} がありません")
        photo.rename(source)

    with Image.open(source) as im:
        framed = frame_to_aspect(im.convert("RGB"), (SHORT_SIZE[0], PHOTO_H))
    framed.save(photo, quality=95)
    print(f"✓ {photo}: {framed.width}x{framed.height}"
          f"（帯 {SHORT_SIZE[0]}x{PHOTO_H} と同じ比率に整えました）")


if __name__ == "__main__":
    main()
