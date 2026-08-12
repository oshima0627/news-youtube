#!/usr/bin/env python3
"""ナレーションに同期したテロップの割り付け。

**音声には一切手を入れない。** VOICEVOX が音声合成に使う内部データ
（`/audio_query` の `accent_phrases`）には、モーラごとの子音長・母音長が
入っている。これを足し上げれば各句が何秒目に読まれるかが分かるので、
音声認識も強制アライメントも要らない。実測で 58.6 秒の読み上げに対して
計算とのずれは 44 ミリ秒だった。

本文と音声の対応づけは句読点で行う。VOICEVOX は読点・句点のところで
アクセント句に `pause_mora` を付けるので、**本文を句読点で切った数と
`pause_mora` で切った数が一致する**（実測25対25）。この対応が崩れたときは
テロップを諦めて静止字幕に戻す（`spans()` が None を返す）。動画が
作れなくなるより、テロップが無い動画のほうがましなので。
"""

from __future__ import annotations

import re

from scripts.draw import normalize_numerals
from scripts.keywords import tokenize

# テロップ1枚の文字数。下帯は58ptで4行まで入るが、読む速さに対して
# 4行は多すぎる。2行に収まる長さで切り替えていく。
MAX_CHARS = 24

# これより短い区切りは次とつなげる。「ポイントは、」だけが0.6秒出て消えるより、
# 続きと一緒に出したほうが読める。
MERGE_UNDER = 12

_SEGMENT_RE = re.compile(r"(?<=[、。！？])")


def split_segments(text: str) -> list[str]:
    """本文を句読点の直後で切る。VOICEVOX の `pause_mora` と対応する単位。"""
    return [s for s in _SEGMENT_RE.split(text) if s.strip()]


def _phrase_duration(phrase: dict) -> float:
    """アクセント句1つの長さ（speedScale を掛ける前の秒数）。"""
    total = sum((m.get("consonant_length") or 0) + (m.get("vowel_length") or 0)
                for m in phrase.get("moras") or [])
    pause = phrase.get("pause_mora")
    if pause:
        total += pause.get("vowel_length") or 0
    return total


def group_durations(query: dict) -> list[float]:
    """`pause_mora` ごとに区切ったアクセント句のかたまりの長さを返す。

    speedScale で割って実時間にする。`prePhonemeLength` は先頭の無音なので
    最初のかたまりに含め、`postPhonemeLength` は末尾に含める。
    """
    speed = query.get("speedScale") or 1.0
    groups: list[float] = []
    current = 0.0
    for phrase in query.get("accent_phrases") or []:
        current += _phrase_duration(phrase)
        if phrase.get("pause_mora"):
            groups.append(current / speed)
            current = 0.0
    if current:
        groups.append(current / speed)
    if groups:
        groups[0] += (query.get("prePhonemeLength") or 0) / speed
        groups[-1] += (query.get("postPhonemeLength") or 0) / speed
    return groups


# 理想の位置から何文字まで離れた切れ目を許すか
_BREAK_WINDOW = 6

# 直後で切ると読みやすい品詞。助詞・助動詞・記号のあとは文節の切れ目になる。
_BREAK_POS = ("助詞", "助動詞", "記号")


def _boundaries(segment: str) -> list[tuple[int, bool]]:
    """形態素の切れ目（文字位置, 文節の切れ目か）の一覧。

    文字数だけで割ると「食料品にかか／る付加価値税」のように語の途中で
    切れる。かといって助詞を1文字ずつ照合すると、「かかる」の「か」を
    助詞と見なして同じ場所で切ってしまう。品詞を見るのが確実で、
    形態素解析器は検索語の抽出（keywords.py）で既に使っている。
    """
    out: list[tuple[int, bool]] = []
    pos = 0
    for token in tokenize(segment):
        pos += len(token.surface)
        if pos >= len(segment):
            break
        out.append((pos, token.part_of_speech.split(",")[0] in _BREAK_POS))
    return out


def _split_point(segment: str, target: int) -> int:
    """target の近くで、語の切れ目になっている位置を探す。

    文節の切れ目を最優先し、無ければ形態素の切れ目、それも無ければ
    target をそのまま使う（切れないよりは語中で切るほうがまし）。
    """
    near = [(p, phrase) for p, phrase in _boundaries(segment)
            if abs(p - target) <= _BREAK_WINDOW]
    for phrase_only in (True, False):
        picked = [p for p, phrase in near if phrase or not phrase_only]
        if picked:
            return min(picked, key=lambda p: abs(p - target))
    return target


def _chunk(segment: str, seconds: float) -> list[tuple[str, float]]:
    """長すぎる区切りを MAX_CHARS 以下に割り、時間も文字数の比で分ける。

    区切りの中のどこで音が変わるかまでは対応づけられないので、文字数の比で
    按分する。1区切りは1〜3秒なので、ここで生じるずれは数百ミリ秒に収まる。
    """
    if len(segment) <= MAX_CHARS:
        return [(segment, seconds)]

    parts = -(-len(segment) // MAX_CHARS)          # 切り上げ
    pieces: list[str] = []
    rest = segment
    for remaining in range(parts, 1, -1):
        cut = _split_point(rest, -(-len(rest) // remaining))
        pieces.append(rest[:cut])
        rest = rest[cut:]
    pieces.append(rest)
    pieces = [p for p in pieces if p]
    return [(p, seconds * len(p) / len(segment)) for p in pieces]


def spans(text: str, query: dict) -> list[tuple[str, float, float]] | None:
    """(テロップ, 開始秒, 終了秒) の並びを返す。対応が取れなければ None。

    None を返すのは、本文の句読点の数と VOICEVOX の区切りの数が食い違った
    ときだけ。無理に割り当てると音とずれたテロップが出続けるので、
    呼び出し側は静止字幕に戻す。
    """
    segments = split_segments(text)
    durations = group_durations(query)
    if not segments or len(segments) != len(durations):
        print(f"! テロップの割り付けを見送ります（本文の区切り{len(segments)}個に対し"
              f"音声の区切り{len(durations)}個）")
        return None

    merged: list[tuple[str, float]] = []
    for segment, seconds in zip(segments, durations):
        if merged and len(merged[-1][0]) < MERGE_UNDER:
            prev_text, prev_seconds = merged.pop()
            segment, seconds = prev_text + segment, prev_seconds + seconds
        merged.extend(_chunk(segment, seconds))

    out: list[tuple[str, float, float]] = []
    start = 0.0
    for chunk_text, seconds in merged:
        # 引用カードと同じく、画面に出す直前に漢数字を算用数字へ直す。
        # 読み上げは元の文字列で行われているので音とはずれない。
        out.append((normalize_numerals(chunk_text), start, start + seconds))
        start += seconds
    return out


def stretch(items: list[tuple[str, float, float]],
            duration: float) -> list[tuple[str, float, float]]:
    """合計をちょうど duration に合わせる。

    区切りごとの計算値を足し上げた総尺は wav の実尺と数十ミリ秒ずれる。
    そのまま使うと最後のテロップが早く消えたり、映像が音より長くなる。
    比で引き伸ばして端を合わせる。
    """
    if not items or duration <= 0:
        return items
    total = items[-1][2]
    if total <= 0:
        return items
    ratio = duration / total
    return [(t, s * ratio, e * ratio) for t, s, e in items]
