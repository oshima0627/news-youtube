"""TikTok 用の台本（410〜450字）を読む load_tiktok_script の単体テスト。

ショート用の load_script と同じく source_url の突き合わせを通す。違うのは
字数だけ。字数を外したまま通すと、61秒に届かない動画ができて投稿で弾かれ、
そこまでの音声合成と動画合成が無駄になる。**読んだ時点で止める。**
"""

from __future__ import annotations

import json

import pytest

from scripts.script_writer import (
    TIKTOK_MAX_CHARS,
    TIKTOK_MIN_CHARS,
    ScriptMismatch,
    load_tiktok_script,
)

SOURCE = "https://kokkai.ndl.go.jp/txt/122105254X02320260604/16"
EVIDENCE = {"source_url": SOURCE}


def _script(narration_chars=430, **over):
    data = {
        "source_url": SOURCE,
        "title": "出生数67万人・出生率1.14 国会で示された「二つの少子化対策」",
        "headline": "出生数67万人",
        "narration": "あ" * narration_chars,
        "subtitle": "過去最低を更新し続けている",
        "quote_excerpt": "出生数は六十七万人",
        "figure_label": "",
        "figure_value": "",
        "tags": ["少子化", "出生数", "国会"],
    }
    data.update(over)
    return data


def _write(tmp_path, data):
    path = tmp_path / "script.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_窓のなかの台本を読める(tmp_path):
    script = load_tiktok_script(_write(tmp_path, _script()), EVIDENCE)
    assert script.headline == "出生数67万人"
    assert len(script.narration) == 430


def test_一次資料が違えば受け付けない(tmp_path):
    path = _write(tmp_path, _script(source_url="https://example.com/other"))
    with pytest.raises(ScriptMismatch):
        load_tiktok_script(path, EVIDENCE)


def test_本文が短すぎれば受け付けない(tmp_path):
    path = _write(tmp_path, _script(narration_chars=TIKTOK_MIN_CHARS - 1))
    with pytest.raises(ScriptMismatch):
        load_tiktok_script(path, EVIDENCE)


def test_本文が長すぎれば受け付けない(tmp_path):
    path = _write(tmp_path, _script(narration_chars=TIKTOK_MAX_CHARS + 1))
    with pytest.raises(ScriptMismatch):
        load_tiktok_script(path, EVIDENCE)


def test_下限ちょうどは通す(tmp_path):
    load_tiktok_script(
        _write(tmp_path, _script(narration_chars=TIKTOK_MIN_CHARS)), EVIDENCE)


def test_上限ちょうどは通す(tmp_path):
    load_tiktok_script(
        _write(tmp_path, _script(narration_chars=TIKTOK_MAX_CHARS)), EVIDENCE)


def test_字数を外したときのメッセージに実際の字数と範囲が出る(tmp_path):
    path = _write(tmp_path, _script(narration_chars=300))
    with pytest.raises(ScriptMismatch) as e:
        load_tiktok_script(path, EVIDENCE)
    assert "300" in str(e.value)
    assert str(TIKTOK_MIN_CHARS) in str(e.value)


def test_ショート用の330字台本はTikTok用として弾かれる(tmp_path):
    """--script と --tiktok-script を取り違えたときに気づけること。"""
    path = _write(tmp_path, _script(narration_chars=340))
    with pytest.raises(ScriptMismatch):
        load_tiktok_script(path, EVIDENCE)
