"""TikTok 投稿の関門と純関数の単体テスト。

投稿そのものは外部APIなのでモックするが、**投稿を止める判断**は
ここで全部潰しておく。止められなかった場合の損失が大きい順に:

  1. 尺が60秒以下 → Creator Rewards の対象外。成功ログだけ出て価値がゼロ
  2. 未審査 → 投稿は通るが全部 SELF_ONLY。誰にも届かないまま積み上がる
  3. アカウント取り違え → 別アカウントに出る。消して出し直すことになる
"""

from __future__ import annotations

import pytest

from scripts import tiktok


def _meta(**over):
    meta = {
        "id": "abc123",
        "title": "出生数67万人・出生率1.14 国会で示された「二つの少子化対策」",
        "tags": ["少子化", "出生数", "国会"],
        "source_url": "https://kokkai.ndl.go.jp/txt/122105254X02320260604/16",
        "source_context": "第221回国会 衆議院本会議 2026-06-04 高山聡史",
        "expected_tiktok_open_id": "open-abc",
    }
    meta.update(over)
    return meta


def _creator_info(**over):
    info = {
        "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
        "max_video_post_duration_sec": 600,
        "creator_username": "newsmarukawa",
    }
    info.update(over)
    return info


# ── 1. 尺の関門 ────────────────────────────────────────────────

def test_60秒ちょうどの動画は投稿を止める():
    with pytest.raises(tiktok.VideoTooShort):
        tiktok.assert_over_a_minute(60.0)


def test_61秒未満の動画は投稿を止める():
    with pytest.raises(tiktok.VideoTooShort):
        tiktok.assert_over_a_minute(60.9)


def test_窓どおりの75秒は通す():
    tiktok.assert_over_a_minute(75.0)


def test_尺が足りないときのメッセージに実尺と下限が出る():
    with pytest.raises(tiktok.VideoTooShort) as e:
        tiktok.assert_over_a_minute(58.42)
    assert "58.42" in str(e.value)
    assert "61" in str(e.value)


# ── 2. 未審査ガード ────────────────────────────────────────────

def test_公開が選べるならPUBLIC_TO_EVERYONEを返す():
    assert tiktok.resolve_privacy_level(_creator_info()) == "PUBLIC_TO_EVERYONE"


def test_未審査で公開が選べないなら投稿を止める():
    info = _creator_info(privacy_level_options=["SELF_ONLY"])
    with pytest.raises(tiktok.NotAudited):
        tiktok.resolve_privacy_level(info)


def test_未審査でもallow_self_onlyを明示すればSELF_ONLYで通す():
    info = _creator_info(privacy_level_options=["SELF_ONLY"])
    assert tiktok.resolve_privacy_level(
        info, allow_self_only=True) == "SELF_ONLY"


def test_allow_self_onlyでも公開が選べるなら公開を優先する():
    assert tiktok.resolve_privacy_level(
        _creator_info(), allow_self_only=True) == "PUBLIC_TO_EVERYONE"


def test_アカウントが投稿できる尺を超えていたら止める():
    info = _creator_info(max_video_post_duration_sec=60)
    with pytest.raises(tiktok.VideoTooLong):
        tiktok.assert_duration_allowed(75.0, info)


def test_アカウントの上限内なら通す():
    tiktok.assert_duration_allowed(75.0, _creator_info())


# ── 3. アカウント取り違えガード ────────────────────────────────

def test_open_idが一致すれば通す():
    tiktok.assert_expected_account("open-abc", _meta())


def test_open_idが違えば投稿を止める():
    with pytest.raises(tiktok.AccountMismatch):
        tiktok.assert_expected_account("open-xyz", _meta())


def test_metaにexpected_tiktok_open_idが無ければ投稿を止める():
    meta = _meta()
    del meta["expected_tiktok_open_id"]
    with pytest.raises(tiktok.AccountMismatch):
        tiktok.assert_expected_account("open-abc", meta)


# ── 4. キャプション ────────────────────────────────────────────

def test_キャプションにタイトルと出典とハッシュタグが入る():
    caption = tiktok.build_caption(_meta())
    assert "二つの少子化対策" in caption
    assert "衆議院本会議 2026-06-04 高山聡史" in caption
    assert "https://kokkai.ndl.go.jp/txt/122105254X02320260604/16" in caption
    assert "#少子化" in caption
    assert "#出生数" in caption


def test_キャプションは2200runeを超えない():
    caption = tiktok.build_caption(_meta(title="あ" * 3000))
    assert tiktok.utf16_len(caption) <= tiktok.CAPTION_MAX_RUNES


def test_タイトルが長すぎても出典URLは残る():
    caption = tiktok.build_caption(_meta(title="あ" * 3000))
    assert "https://kokkai.ndl.go.jp/txt/122105254X02320260604/16" in caption


def test_utf16_lenは絵文字を2でかぞえる():
    assert tiktok.utf16_len("あ") == 1
    assert tiktok.utf16_len("🎌") == 2


# ── 5. 尺の窓と字数の対応 ──────────────────────────────────────
#
# 「台本に頼む字数」「音声合成が狙う窓」「投稿を止める下限」の3つが
# 食い違うと、字数どおりに書いた台本から61秒未満の動画ができて投稿で
# 弾かれる。3つの関係をここで縛る（test_script_writer.py の同じ形）。

def test_狙う窓は投稿の下限より上にある():
    assert tiktok.TIKTOK_TARGET_MIN > tiktok.TIKTOK_MIN_SECONDS


def test_頼む字数はそのまま読んだとき狙う窓に入る():
    from scripts.narrate import SECONDS_PER_CHAR
    from scripts.script_writer import TIKTOK_MAX_CHARS, TIKTOK_MIN_CHARS

    for chars in (TIKTOK_MIN_CHARS, TIKTOK_MAX_CHARS):
        seconds = chars * SECONDS_PER_CHAR
        assert tiktok.TIKTOK_TARGET_MIN <= seconds <= tiktok.TIKTOK_TARGET_MAX, (
            f"{chars}字は{seconds:.1f}秒で、狙う窓 "
            f"{tiktok.TIKTOK_TARGET_MIN}〜{tiktok.TIKTOK_TARGET_MAX}秒の外")
