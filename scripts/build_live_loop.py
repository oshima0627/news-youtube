#!/usr/bin/env python3
"""recipes/*.json から常時配信用のループ動画を1本組む。

  python scripts/build_live_loop.py --out work/live/loop.mp4

読み上げるのは 見出し / 一次資料の逐語引用 / 出典 の3つだけ。
モデルが書いた文字列は1文字も入らない。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

from PIL import Image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

from scripts.audio_mix import mix  # noqa: E402
from scripts.cards_wide import (BODY_TOP, CARD_W, WIDE_SIZE,  # noqa: E402
                                render_headline, render_quote)
from scripts.draw import NAVY  # noqa: E402
from scripts.evidence import ground_excerpt  # noqa: E402
from scripts.narrate import (SECONDS_PER_CHAR, synthesize,  # noqa: E402
                             wav_duration_seconds)

RECIPES_DIR = ROOT / "recipes"

# 推定尺に対して許容する上下の幅。ショートの 56〜61秒（±4%）より広いのは、
# ライブの1題材が引用文の長さでばらつくため。狭いと毎回警告が出て、
# 無音や合成失敗という本物の異常がその警告に埋もれる。
#
# **上下は対称にする。** `narrate.synthesize` は窓の中央値を狙って
# speedScale を補正するので、上だけ広い窓（0.70/1.40）を渡すと中央値が
# 推定尺の1.05倍になり、全題材が一律に約5%遅く読まれる。
WINDOW_LOW = 0.70
WINDOW_HIGH = 1.30


class ExcludeCategoryNotFound(ValueError):
    """除外指定したカテゴリが `recipes/` に1件も無かった。

    投票日の選挙関連除外（公職選挙法129条）が、綴り違いで黙って
    素通りするのを防ぐ。**警告ではなく例外で止める。**
    """


def select_recipes(recipes_dir: Path, *,
                   exclude_categories: frozenset[str] = frozenset()) -> list[dict]:
    """ループに載せるレシピを id 昇順で返す。

    `exclude_categories` は投票日に選挙関連を外すためにある
    （公職選挙法129条。動き続ける配信は継続的な公開行為にあたる）。
    **実データの選挙カテゴリは `"election"`**（`run_election.py` が書く値。
    `run_daily.py` が書く値は `"政治"`）。

    指定したカテゴリが1件も一致しなかったら `ExcludeCategoryNotFound` で
    止める。一致しない除外を黙って通すと、投票日に
    `--exclude-category 選挙` と打った運用者には除外なしと同じ件数が出て、
    選挙関連が投票日を跨いで流れ続ける。**関門が黙って空振りするのは、
    関門を呼び出し側に置くのと同じ穴。**
    """
    exclude = frozenset(exclude_categories)
    dropped = {name: 0 for name in exclude}
    seen: set[str] = set()
    out = []
    for path in sorted(Path(recipes_dir).glob("*.json")):
        recipe = json.loads(path.read_text(encoding="utf-8"))
        category = recipe.get("category")
        if category is not None:
            seen.add(category)
        if category in exclude:
            dropped[category] += 1
            continue
        out.append(recipe)

    missed = sorted(name for name, count in dropped.items() if count == 0)
    if missed:
        raise ExcludeCategoryNotFound(
            f"除外指定 {missed} に一致するレシピが {Path(recipes_dir)} に1件もありません。"
            f"実在するカテゴリ: {sorted(seen)}")
    for name in sorted(dropped):
        print(f"- 除外 {name}: {dropped[name]}件")
    return sorted(out, key=lambda r: r["id"])


def shuffle_for_date(recipes: list[dict], day: date) -> list[dict]:
    """その日のループの並び順。**日付だけから決まる（同じ日なら同じ順）。**

    設計書の「`loop.mp4` は順序をシャッフルし…毎日ビルドし直す」。
    id は16進のハッシュなので id 昇順のままだと毎日ほぼ同じ並びになり、
    11.5時間のアーカイブに同じ順序の同じ内容が約17回入る（量産型判定）。

    乱数の種を日付にしてあるのは、**同じ日に作り直しても同じ順序に
    なる**ようにするため。実行のたびに変わると、ビルドが失敗して
    やり直したときに何が変わったのか追えない。
    """
    order = list(recipes)
    random.Random(day.isoformat()).shuffle(order)
    return order


def narration_text(recipe: dict) -> str:
    """読み上げる文字列。**見出し・逐語引用・出典の連結だけ。**

    ここに定型の地の文（「続いてのニュースです」等）を足さないこと。
    足した瞬間、一次資料に無い文字列が出典キャプション付きで読み上げられ、
    「一次資料が取れなければ公開しない」がこの経路だけ破れる。
    """
    ev = recipe["evidence"]
    return "\n".join([recipe["headline"], ev["quote"], ev["context"]])


# ------------------------------------------------------------ 引用の分割
#
# 引用カード（`cards_wide.render_quote`）に収まるのは 32px・6行で約165字。
# 実データの引用文は中央値222字で、**57件中38件が2〜3行あふれて
# 切り捨てられていた**。ナレーションは引用文を最後まで読むので、
# 切り捨てると「聞こえているのに画面に無い」状態が大半の時間で続く。
# 画面に出るのが引用カードだけの動画でこれは成立しない。
#
# → **切り捨てず、収まる単位に分けて複数フレームで見せる。**
#   分割は文末（。！？）を優先し、1文で収まらなければ読点、それでも
#   収まらなければ文字数で切る。どの断片も**引用文の連続した部分文字列**で、
#   つなぎ直すと元の引用文に戻る（省略記号すら足さない）。

SENTENCE_END = "。！？!?"
CLAUSE_END = "、，,"

_MARK = "! 引用が"          # cards_wide.render_quote があふれを知らせる書式
_detector_checked = False


def _render_quote_quiet(text: str, source: str) -> tuple[Image.Image, bool]:
    """引用カードを描き、**あふれたかどうか**を一緒に返す。

    収まるかどうかの判定を自前で書き直さない。フォント・折り返し・行数の
    上限は `cards_wide.render_quote` の中にあり、同じ計算をここに写すと
    判定基準が2箇所に分かれて必ず食い違う（CLAUDE.md）。実物に描かせて、
    実物が出すあふれ警告をそのまま判定に使う。

    分割の途中でどれだけ試し描きしてもログは汚さない（あふれ警告だけ
    握りつぶす）。出典のあふれなど他の警告は本物の異常なので素通しする。
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        img = render_quote(text, source)
    # 警告は1件が複数行になりうる（末尾に載る引用文の先頭20字に改行が入る）。
    # 行単位で仕分けると、あふれ警告の2行目だけが素通りしてログに出る。
    records: list[str] = []
    for line in buf.getvalue().splitlines():
        if line.startswith("! ") or not records:
            records.append(line)
        else:
            records[-1] += "\n" + line
    overflowed = False
    for record in records:
        if record.startswith(_MARK):
            overflowed = True
        elif record.strip():
            print(record)
    return img, overflowed


def _quote_overflows(text: str, source: str) -> bool:
    return _render_quote_quiet(text, source)[1]


def _assert_detector_works(source: str) -> None:
    """あふれ検出そのものが効いているかを1回だけ確かめる。

    判定は `render_quote` の警告文の書式に乗っている。書式が変われば
    検出は黙って「常に収まる」に倒れ、また38件が切り捨てられる状態に
    戻る。**黙って戻らないよう、ここで落とす。**
    """
    global _detector_checked
    if _detector_checked:
        return
    if not _quote_overflows("あ" * 2000, source):
        raise RuntimeError(
            "cards_wide.render_quote のあふれ警告を検出できません"
            f"（'{_MARK}' で始まる行を探しています）。書式が変わった可能性があります。")
    _detector_checked = True


def _split_keeping(text: str, delimiters: str) -> list[str]:
    """区切り文字を残したまま切る。**つなぎ直すと元に戻る。**"""
    parts, buf = [], ""
    for ch in text:
        buf += ch
        if ch in delimiters:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts


def _max_fitting_prefix(text: str, source: str) -> int:
    """`text` の先頭から、カードに収まる最長の長さを返す（1以上）。"""
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _quote_overflows(text[:mid], source):
            hi = mid - 1
        else:
            lo = mid
    # 折り返しは厳密には単調でないので、二分探索の結果を実物で確かめ直す
    while lo > 1 and _quote_overflows(text[:lo], source):
        lo -= 1
    return lo


def _atoms(text: str, source: str) -> list[str]:
    """それ以上分けなくてもカードに収まる断片に刻む。"""
    out = []
    for sentence in _split_keeping(text, SENTENCE_END):
        if not _quote_overflows(sentence, source):
            out.append(sentence)
            continue
        for clause in _split_keeping(sentence, CLAUSE_END):
            rest = clause
            while rest and _quote_overflows(rest, source):
                cut = _max_fitting_prefix(rest, source)
                out.append(rest[:cut])
                rest = rest[cut:]
            if rest:
                out.append(rest)
    return out


def split_quote_for_cards(quote: str, source: str) -> list[str]:
    """引用文をカードに収まる断片の列にする。

    返る断片はどれも `quote` の**連続した部分文字列**で、順につなぎ直すと
    `quote` そのものに戻る（`tests/test_build_live_loop.py` が縛っている）。
    省略記号も空白の詰めも行わない。1文字でも足したり削ったりすると、
    出典キャプション付きのカードに一次資料に無い文字列が出ることになる。
    """
    if not quote:
        return [quote]
    _assert_detector_works(source)
    frames: list[str] = []
    current = ""
    for atom in _atoms(quote, source):
        if current and _quote_overflows(current + atom, source):
            frames.append(current)
            current = atom
        else:
            current += atom
    if current:
        frames.append(current)
    return frames or [quote]


def split_durations(pieces: list[str], total: float) -> list[float]:
    """1題材の音声の尺を、断片の字数比で分ける。合計は `total` に一致する。"""
    weights = [max(len(p), 1) for p in pieces]
    denom = sum(weights)
    out, used = [], 0.0
    for w in weights[:-1]:
        d = total * w / denom
        out.append(d)
        used += d
    out.append(total - used)
    return out


def render_frame(recipe: dict, quote_text: str | None = None) -> Image.Image:
    """1題材ぶんの静止画。**写真枠は使わない。**

    50件ぶんの写真が work/ から消えており、取り直すと人物写真の
    取り違えリスクを新しい経路に持ち込む（CLAUDE.md）。

    引用カードは横中央に置く（写真枠 CARD_LEFT ではない）。CARD_LEFT は
    左に実写を置く前提の座標で、写真を使わないこの設計でそのまま使うと
    画面の左半分が紺色の空白になる。

    `quote_text` は `split_quote_for_cards` が切り出した断片。省略すると
    引用文の全体を1枚に載せる（カードに収まらなければ `render_quote` が
    あふれを警告する。ここでは握りつぶさない）。
    """
    ev = recipe["evidence"]
    base = Image.new("RGB", WIDE_SIZE, NAVY)
    base.paste(render_headline(recipe["headline"]), (0, 0))
    # ground_excerpt を通すことで、カードに出る文字列が逐語引用であることを担保する
    quote = ground_excerpt(ev["quote"] if quote_text is None else quote_text, ev["quote"])
    base.paste(render_quote(quote, ev["context"]),
               ((WIDE_SIZE[0] - CARD_W) // 2, BODY_TOP))
    return base


def speech_window(text: str) -> tuple[float, float]:
    """`narrate.synthesize` に渡す尺の窓を文字数から決める。"""
    est = max(len(text) * SECONDS_PER_CHAR, 1.0)
    return est * WINDOW_LOW, est * WINDOW_HIGH


def build(out_path: Path, recipes: list[dict], *, workdir: Path | None = None,
          day: date | None = None) -> Path:
    """レシピを順に読み上げた16:9のループ用 mp4 を1本書き出す。

    配信側は再エンコードしない（`-c copy`）ので、ここで
    YouTube ライブに載る形（h264 + aac・2秒GOP）まで作り切る。

    並び順は `day`（既定は今日）から決まるシャッフル。1題材の画面は
    引用が長ければ複数枚になり、その題材の音声の尺を字数比で分け合う。
    """
    if not recipes:
        # 空のまま進めると frames[-1] が素の IndexError で落ち、
        # 「レシピが0件だった」という本当の原因が読み取れなくなる。
        raise ValueError("recipes が空です。1件以上のレシピが必要です。")

    out_path = Path(out_path)
    work = Path(workdir) if workdir else out_path.parent / "parts"
    work.mkdir(parents=True, exist_ok=True)
    recipes = shuffle_for_date(recipes, day or date.today())

    frames, wavs = [], []
    for i, recipe in enumerate(recipes):
        text = narration_text(recipe)
        lo, hi = speech_window(text)
        raw = work / f"{i:03d}_voice.wav"
        synthesize(text, raw, target_min=lo, target_max=hi)
        mixed = work / f"{i:03d}_mixed.wav"
        mix(raw, mixed)                      # BGM の関門はここ1箇所だけ
        wavs.append(mixed)
        ev = recipe["evidence"]
        pieces = split_quote_for_cards(ev["quote"], ev["context"])
        durations = split_durations(pieces, wav_duration_seconds(mixed))
        for j, (piece, dur) in enumerate(zip(pieces, durations)):
            png = work / f"{i:03d}_{j:02d}.png"
            render_frame(recipe, piece).save(png)
            frames.append((png, dur))

    # concat の行はファイル名だけを書く（`build_long._concat_audio` と同じ）。
    # ffmpeg はこのパスを **concat ファイルが置かれている場所** から解決するので、
    # cwd 基準の相対パスを書くと parts/parts/000_00.png のように二重になり、
    # 1枚も開けない。素材は concat ファイルと同じ work に置いてある。
    audio_list = work / "audio.txt"
    audio_list.write_text(
        "\n".join(f"file '{w.name}'" for w in wavs) + "\n", encoding="utf-8")
    frame_list = work / "frames.txt"
    lines = []
    for png, dur in frames:
        lines.append(f"file '{png.name}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{frames[-1][0].name}'")   # concat は最後を2度書く
    frame_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(frame_list),
        "-f", "concat", "-safe", "0", "-i", str(audio_list),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-g", "60", "-keyint_min", "60",     # 2秒GOP。YouTube ライブの要件
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-shortest", str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace")
    except subprocess.CalledProcessError as e:
        # build_long.py と同じ形にする。check=True だけに任せると、
        # 例外の repr に stderr が出ずに失敗原因が読み取れない。
        raise RuntimeError(
            f"ffmpegの実行に失敗しました（frames={frame_list}, audio={audio_list}）:\n"
            f"{e.stderr}") from e
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "work" / "live" / "loop.mp4")
    # 投票日は `--exclude-category election`。綴りが実データに無ければ例外で止まる。
    ap.add_argument("--exclude-category", action="append", default=[],
                    help="除外するカテゴリ（例: election）。繰り返し指定できる")
    args = ap.parse_args()
    recipes = select_recipes(RECIPES_DIR,
                             exclude_categories=frozenset(args.exclude_category))
    print(f"- レシピ {len(recipes)}件")
    path = build(args.out, recipes)
    print(f"✓ {path}")


if __name__ == "__main__":
    main()
