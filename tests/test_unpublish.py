"""unpublish.py は完全自動公開に対する唯一の緊急停止手段なので、
YouTube API をモックして単体で検証する。

とくに --all-today が当日 publish_at の動画だけを拾うことと、
state/published.json が無い/壊れているときに沈黙せず原因つきで
落ちることを確認する。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from scripts import unpublish


def _published(tmp_path, videos: dict) -> None:
    path = tmp_path / "published.json"
    path.write_text(json.dumps({"videos": videos}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _fake_service():
    return object()


def test_all_todayは当日のpublish_atを持つ動画だけを選ぶ(tmp_path, monkeypatch):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    path = _published(tmp_path, {
        "a": {"youtube_video_id": "vid_today", "publish_at": f"{today}T07:30:00+09:00"},
        "b": {"youtube_video_id": "vid_yesterday", "publish_at": f"{yesterday}T07:30:00+09:00"},
        "c": {"youtube_video_id": "vid_tomorrow", "publish_at": f"{tomorrow}T07:30:00+09:00"},
        "d": {"youtube_video_id": "vid_no_schedule"},
    })
    monkeypatch.setattr(unpublish, "PUBLISHED", path)

    calls = []
    monkeypatch.setattr(unpublish, "get_service", _fake_service)
    monkeypatch.setattr(unpublish, "set_privacy",
                        lambda service, vid, privacy: calls.append((vid, privacy)))
    monkeypatch.setattr("sys.argv", ["unpublish.py", "--all-today"])

    unpublish.main()

    assert calls == [("vid_today", "private")]


def test_video_id直接指定でその1件だけが対象になる(monkeypatch):
    calls = []
    monkeypatch.setattr(unpublish, "get_service", _fake_service)
    monkeypatch.setattr(unpublish, "set_privacy",
                        lambda service, vid, privacy: calls.append((vid, privacy)))
    monkeypatch.setattr("sys.argv", ["unpublish.py", "specific_vid"])

    unpublish.main()

    assert calls == [("specific_vid", "private")]


def test_対象がないときAPIを呼ばずに終了する(tmp_path, monkeypatch, capsys):
    path = _published(tmp_path, {})
    monkeypatch.setattr(unpublish, "PUBLISHED", path)

    def _boom():
        raise AssertionError("対象がないのに get_service を呼んでいる")

    monkeypatch.setattr(unpublish, "get_service", _boom)
    monkeypatch.setattr("sys.argv", ["unpublish.py", "--all-today"])

    unpublish.main()

    assert "対象がありません" in capsys.readouterr().out


def test_引数なしでもAPIを呼ばずに終了する(monkeypatch, capsys):
    def _boom():
        raise AssertionError("対象がないのに get_service を呼んでいる")

    monkeypatch.setattr(unpublish, "get_service", _boom)
    monkeypatch.setattr("sys.argv", ["unpublish.py"])

    unpublish.main()

    assert "対象がありません" in capsys.readouterr().out


def test_published_jsonが存在しないときは原因つきで落ちる(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(unpublish, "PUBLISHED", tmp_path / "does_not_exist.json")
    monkeypatch.setattr("sys.argv", ["unpublish.py", "--all-today"])

    with pytest.raises(SystemExit):
        unpublish.main()

    err = capsys.readouterr().err
    assert "published.json" in err or "does_not_exist.json" in err


def test_published_jsonが壊れているときは原因つきで落ちる(tmp_path, monkeypatch, capsys):
    path = tmp_path / "published.json"
    path.write_text("{ これはJSONではない", encoding="utf-8")
    monkeypatch.setattr(unpublish, "PUBLISHED", path)
    monkeypatch.setattr("sys.argv", ["unpublish.py", "--all-today"])

    with pytest.raises(SystemExit):
        unpublish.main()

    err = capsys.readouterr().err
    assert err.strip() != ""
