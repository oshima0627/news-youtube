"""run_daily.py の TikTok バリアント（--tiktok-script）のテスト。

引数の組み合わせの検証と、バリアント用の meta.json の中身だけを見る。
実際のビルドと投稿はそれぞれ test_build_short_variant.py /
test_upload_tiktok.py が縛っている。
"""

from __future__ import annotations

import json

import pytest

from scripts import run_daily


def _args(argv):
    import sys
    from unittest import mock
    with mock.patch.object(sys, "argv", ["run_daily.py", *argv]):
        return run_daily.parse_args()


def test_tiktok_scriptはscriptと一緒でないと受け付けない():
    """TikTok 版だけ人の原稿、YouTube 版はモデル生成、という食い違いを作らない。"""
    with pytest.raises(SystemExit):
        _args(["--keyword", "教員 不足", "--tiktok-script", "t.json"])


def test_tiktok_scriptはscriptと併せて指定できる():
    a = _args(["--keyword", "教員 不足", "--script", "s.json",
               "--tiktok-script", "t.json"])
    assert a.tiktok_script == "t.json"


def test_tiktok_scriptを省略すればNone():
    a = _args(["--keyword", "教員 不足", "--script", "s.json"])
    assert a.tiktok_script is None


# ── バリアント用の meta.json ───────────────────────────────────

EVIDENCE = {
    "source_url": "https://kokkai.ndl.go.jp/txt/122105254X02320260604/16",
    "context": "第221回国会 衆議院本会議 2026-06-04 高山聡史",
    "quote": "出生数は六十七万人",
    "figure": "",
}


class _Script:
    title = "出生数67万人・出生率1.14 国会で示された「二つの少子化対策」"
    tags = ["少子化", "出生数", "国会"]


def test_バリアントのmetaには投稿先アカウントが入る(tmp_path, monkeypatch):
    monkeypatch.setattr(run_daily, "TIKTOK_OPEN_ID", "open-abc")
    run_daily.write_tiktok_meta(tmp_path, _Script(), EVIDENCE)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["expected_tiktok_open_id"] == "open-abc"


def test_バリアントのmetaにはキャプションに要る出典が入る(tmp_path, monkeypatch):
    """build_caption が source_context を読む。無いと KeyError で投稿直前に落ちる。"""
    monkeypatch.setattr(run_daily, "TIKTOK_OPEN_ID", "open-abc")
    run_daily.write_tiktok_meta(tmp_path, _Script(), EVIDENCE)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["source_context"] == EVIDENCE["context"]
    assert meta["source_url"] == EVIDENCE["source_url"]


def test_バリアントのmetaからキャプションを組める(tmp_path, monkeypatch):
    from scripts import tiktok

    monkeypatch.setattr(run_daily, "TIKTOK_OPEN_ID", "open-abc")
    run_daily.write_tiktok_meta(tmp_path, _Script(), EVIDENCE)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    caption = tiktok.build_caption(meta)
    assert "二つの少子化対策" in caption
    assert "#少子化" in caption


# ── バリアントのビルド ─────────────────────────────────────────

class _FullScript(_Script):
    narration = "あ" * 430
    headline = "出生数67万人"
    subtitle = "過去最低を更新し続けている"
    quote_excerpt = "出生数は六十七万人"
    figure_label = ""
    figure_value = ""

    def model_dump_json(self, **kw):
        return json.dumps({"narration": self.narration,
                           "headline": self.headline,
                           "subtitle": self.subtitle,
                           "quote_excerpt": self.quote_excerpt},
                          ensure_ascii=False)


@pytest.fixture
def spy(tmp_path, monkeypatch):
    monkeypatch.setattr(run_daily, "TIKTOK_OPEN_ID", "open-abc")
    calls = {}

    def fake_synthesize(text, dest, **kw):
        calls["synthesize"] = {"text": text, "dest": dest, **kw}
        dest.write_bytes(b"wav")
        return dest

    def fake_build(workdir, **kw):
        calls["build"] = {"workdir": workdir, **kw}
        return workdir / "video.mp4"

    monkeypatch.setattr(run_daily, "synthesize", fake_synthesize)
    monkeypatch.setattr(run_daily, "build", fake_build)
    return calls


def test_バリアントはtiktokサブディレクトリに作る(tmp_path, spy):
    workdir = tmp_path / "abc123"
    workdir.mkdir()
    out = run_daily.build_tiktok_variant(workdir, _FullScript(), EVIDENCE)
    assert out == workdir / "tiktok"
    assert (out / "script.json").exists()
    assert (out / "meta.json").exists()


def test_バリアントはTikTokの尺の窓で音声を作る(tmp_path, spy):
    from scripts import tiktok

    workdir = tmp_path / "abc123"
    workdir.mkdir()
    run_daily.build_tiktok_variant(workdir, _FullScript(), EVIDENCE)
    assert spy["synthesize"]["target_min"] == tiktok.TIKTOK_TARGET_MIN
    assert spy["synthesize"]["target_max"] == tiktok.TIKTOK_TARGET_MAX


def test_バリアントは写真とレシピを題材のディレクトリから取る(tmp_path, spy):
    workdir = tmp_path / "abc123"
    workdir.mkdir()
    run_daily.build_tiktok_variant(workdir, _FullScript(), EVIDENCE)
    assert spy["build"]["assets_dir"] == workdir
    assert spy["build"]["recipe_id"] == "abc123"


def test_バリアントもTikTokの尺の窓で動画を検証する(tmp_path, spy):
    from scripts import tiktok

    workdir = tmp_path / "abc123"
    workdir.mkdir()
    run_daily.build_tiktok_variant(workdir, _FullScript(), EVIDENCE)
    assert spy["build"]["target_min"] == tiktok.TIKTOK_TARGET_MIN
    assert spy["build"]["target_max"] == tiktok.TIKTOK_TARGET_MAX


# ── TikTok 側の失敗を YouTube に波及させない ───────────────────

def test_バリアントのビルドが失敗してもNoneを返すだけ(tmp_path, spy, monkeypatch, capsys):
    """TikTok 用の合成や ffmpeg が落ちても、YouTube の予約は続ける。"""
    def boom(workdir, **kw):
        raise RuntimeError("ffmpeg が落ちました")

    monkeypatch.setattr(run_daily, "build", boom)
    workdir = tmp_path / "abc123"
    workdir.mkdir()
    assert run_daily.try_build_tiktok_variant(
        workdir, _FullScript(), EVIDENCE) is None
    assert "TikTok" in capsys.readouterr().out


def test_バリアントのビルドが通ればパスを返す(tmp_path, spy):
    workdir = tmp_path / "abc123"
    workdir.mkdir()
    assert run_daily.try_build_tiktok_variant(
        workdir, _FullScript(), EVIDENCE) == workdir / "tiktok"


# ── 投稿できないバリアントを作らない ───────────────────────────

def test_TikTokの認証が無ければmetaを書かずに止める(tmp_path, monkeypatch):
    """open_id が空だと assert_expected_account が必ず弾く。**作る前に止める。**

    作れてしまうと、音声合成と動画合成を済ませたうえで投稿の直前に落ちる。
    しかも失敗の理由は「meta.json に expected_tiktok_open_id がありません」で、
    原因（TikTok の認証をしていない）から遠い。
    """
    monkeypatch.setattr(run_daily, "TIKTOK_OPEN_ID", "")
    with pytest.raises(run_daily.TikTokNotConfigured):
        run_daily.write_tiktok_meta(tmp_path, _Script(), EVIDENCE)
    assert not (tmp_path / "meta.json").exists()


def test_認証が無いときのメッセージは認証コマンドを案内する(tmp_path, monkeypatch):
    monkeypatch.setattr(run_daily, "TIKTOK_OPEN_ID", "")
    with pytest.raises(run_daily.TikTokNotConfigured) as e:
        run_daily.write_tiktok_meta(tmp_path, _Script(), EVIDENCE)
    assert "--auth-only" in str(e.value)


def test_認証が無いときはビルドも試さない(tmp_path, monkeypatch, spy):
    """try_build_tiktok_variant が握りつぶす前に、音声合成まで行かせない。"""
    monkeypatch.setattr(run_daily, "TIKTOK_OPEN_ID", "")
    workdir = tmp_path / "abc123"
    workdir.mkdir()
    assert run_daily.try_build_tiktok_variant(
        workdir, _FullScript(), EVIDENCE) is None
    assert "synthesize" not in spy
