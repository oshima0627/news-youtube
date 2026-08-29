#!/usr/bin/env python3
"""TikTok 投稿の関門と、投稿に使う純関数。

投稿そのもの（HTTP）は `tiktok_api.py` に置き、ここには **投稿を止める判断**
だけを集めている。CLAUDE.md の「関門は1つにして、全経路がそれを通る」に従い、
`upload_tiktok.post()` からだけ呼ばれる。呼び出し側に判定を散らさない。
"""

from __future__ import annotations

# 投稿を許す実尺の下限（秒）。
#
# TikTok の Creator Rewards Program は 60秒以上の動画だけを対象にしており、
# これが最も多い失格理由。60秒を割った動画は投稿自体は通るので、止めないと
# 「成功ログだけが出て価値がゼロ」の本数が静かに積み上がる。
#
# 60.0 ちょうどではなく 61.0 にしてあるのは、TikTok 側の再エンコードや
# 尺の丸めで 60.0 が 59.9 と判定される余地を消すため。狙う窓は 70〜80秒
# （script_writer.SEGMENT_MIN_CHARS 相当）なので、61.0 は事故の検出線であって
# 通常運転で触る値ではない。
TIKTOK_MIN_SECONDS = 61.0

# 音声合成が狙う実尺の窓（秒）。narrate.synthesize() に渡す。
#
# 長尺の1章（build_long.SEGMENT_TARGET_MIN/MAX）と同じ数字だが、**別に持つ**。
# 長尺の章の長さを変えたときに TikTok の尺まで黙って動くと、下限
# （TIKTOK_MIN_SECONDS）を割ったことに気づけない。両者の対応は
# tests/test_tiktok.py が縛っている。
TIKTOK_TARGET_MIN = 68.0
TIKTOK_TARGET_MAX = 80.0

# キャプションの上限。TikTok の Direct Post API は UTF-16 rune で数える。
CAPTION_MAX_RUNES = 2200

# 終了コード。upload_youtube.py と同じく、**対処が違う失敗を混ぜない**。
#   5 尺不足   → 台本を書き直して作り直す
#   6 未審査   → TikTok の審査を通す（待つ）
#   7 取り違え → 認証をやり直す
EXIT_TOO_SHORT = 5
EXIT_NOT_AUDITED = 6
EXIT_ACCOUNT_MISMATCH = 7


class TikTokError(RuntimeError):
    """TikTok 投稿を止める理由。"""


class VideoTooShort(TikTokError):
    exit_code = EXIT_TOO_SHORT


class VideoTooLong(TikTokError):
    exit_code = EXIT_TOO_SHORT


class NotAudited(TikTokError):
    exit_code = EXIT_NOT_AUDITED


class AccountMismatch(TikTokError):
    exit_code = EXIT_ACCOUNT_MISMATCH


def utf16_len(text: str) -> int:
    """UTF-16 コード単位での長さ。TikTok がキャプションを数える単位。

    日本語（BMP）は1、絵文字などのサロゲートペアは2で数える。`len()` の
    コードポイント数とはズレるので、上限判定はこちらを使う。
    """
    return len(text.encode("utf-16-le")) // 2


def assert_over_a_minute(duration: float) -> None:
    """実尺が 60秒を超えていなければ投稿を止める。"""
    if duration < TIKTOK_MIN_SECONDS:
        raise VideoTooShort(
            f"実尺が{duration:.2f}秒で、下限の{TIKTOK_MIN_SECONDS:.0f}秒に"
            "届いていません。60秒以下の動画は TikTok の Creator Rewards の"
            "対象外なので投稿しません。台本を410〜450字に伸ばして作り直して"
            "ください")


def assert_duration_allowed(duration: float, creator_info: dict) -> None:
    """このアカウントが投稿できる尺の上限を超えていないか。

    上限はアカウントごとに違い、`creator_info/query` が返す。超えたまま
    送ると init は通って後段で失敗するので、送る前に止める。
    """
    limit = creator_info.get("max_video_post_duration_sec")
    if limit is not None and duration > limit:
        raise VideoTooLong(
            f"実尺{duration:.2f}秒が、このアカウントの投稿上限"
            f"{limit}秒を超えています")


def resolve_privacy_level(creator_info: dict,
                          allow_self_only: bool = False) -> str:
    """投稿に使う公開範囲を決める。公開が選べなければ止める。

    未審査のクライアントが投稿したものは **すべて SELF_ONLY に強制される**。
    投稿API自体は成功を返すので、止めないと「誰にも届かない動画」を
    成功ログ付きで作り続けることになる。審査が下りたかどうかは
    `privacy_level_options` に PUBLIC_TO_EVERYONE が現れるかで判る。
    """
    options = creator_info.get("privacy_level_options") or []
    if "PUBLIC_TO_EVERYONE" in options:
        return "PUBLIC_TO_EVERYONE"
    if allow_self_only and "SELF_ONLY" in options:
        return "SELF_ONLY"
    raise NotAudited(
        "このアカウントで公開投稿（PUBLIC_TO_EVERYONE）が選べません。"
        f"選べるのは {options or '（なし）'} だけです。"
        "TikTok アプリの video.publish 審査が未了だと、投稿しても"
        "すべて自分だけ表示になります。経路の確認だけなら "
        "--allow-self-only を付けてください")


def assert_expected_account(open_id: str, meta: dict) -> None:
    """meta の expected_tiktok_open_id と一致しない限り投稿しない。

    間違ったアカウントに出すと消して出し直すことになる。出す前に止めるほうが安い
    （upload_youtube.assert_expected_channel と同じ判断）。
    """
    expected = meta.get("expected_tiktok_open_id")
    if not expected:
        raise AccountMismatch(
            "meta.json に expected_tiktok_open_id がありません。"
            "取り違えを防げないので投稿しません")
    if open_id != expected:
        raise AccountMismatch(
            "投稿先のアカウントが指定と一致しません。\n"
            f"  期待: {expected}\n"
            f"  実際: {open_id}\n"
            "  tiktok_token.json を削除し、正しいアカウントで認証し直してください")


def build_caption(meta: dict) -> str:
    """投稿のキャプションを組む。

    description.txt は YouTube 向け（5000字・リンクが踏める前提）なので
    そのままは使えない。TikTok は 2200 UTF-16 rune 上限で、本文中のURLは
    踏めないがテキストとしては残る（出典を追える形にはしておく）。

    **モデルには書かせない。** 一次資料に紐づかない文をここで増やさないため、
    meta にある値だけを並べる。
    """
    tags = " ".join(f"#{t}" for t in meta.get("tags", []))
    tail_parts = [
        f"根拠: {meta['source_context']}",
        meta["source_url"],
    ]
    if tags:
        tail_parts.append(tags)
    tail = "\n\n" + "\n".join(tail_parts[:2]) + (f"\n\n{tags}" if tags else "")

    budget = CAPTION_MAX_RUNES - utf16_len(tail)
    title = meta["title"]
    if utf16_len(title) > budget:
        # 出典URLを削るとどの一次資料か辿れなくなる。削るのはタイトル側。
        while title and utf16_len(title) > budget:
            title = title[:-1]
    return title + tail
