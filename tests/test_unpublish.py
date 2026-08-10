"""unpublish.py は完全自動公開に対する唯一の緊急停止手段なので、
YouTube API をモックして単体で検証する。

とくに --all-today が当日 publish_at の動画だけを拾うこと、その判定が
ホストのローカルタイムゾーンに依存せず JST の暦日で行われること、
パース不能な publish_at を黙って無視しないこと、そして
state/published.json が無い/壊れているときに沈黙せず原因つきで
落ちることを確認する。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from scripts import unpublish


def _published(tmp_path, videos: dict) -> None:
    path = tmp_path / "published.json"
    path.write_text(json.dumps({"videos": videos}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _fake_service():
    return object()


def _freeze_now(monkeypatch, instant: datetime) -> None:
    """unpublish.datetime.now() を固定する。

    ホストの実際のタイムゾーンに関係なく `today_jst` を決定できるようにし、
    「たまたま実行環境がJSTだったから通った」という偽陽性を排除する。
    """
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant

    monkeypatch.setattr(unpublish, "datetime", _Frozen)


def test_all_todayは当日のpublish_atを持つ動画だけを選ぶ(tmp_path, monkeypatch):
    _freeze_now(monkeypatch, datetime(2026, 8, 11, 12, 0, tzinfo=unpublish.JST))

    path = _published(tmp_path, {
        "a": {"youtube_video_id": "vid_today", "publish_at": "2026-08-11T07:30:00+09:00"},
        "b": {"youtube_video_id": "vid_yesterday", "publish_at": "2026-08-10T07:30:00+09:00"},
        "c": {"youtube_video_id": "vid_tomorrow", "publish_at": "2026-08-12T07:30:00+09:00"},
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


def test_all_todayはホストのローカルタイムゾーンに依存せずJSTの暦日で判定する(tmp_path, monkeypatch):
    # 「いま」を JST 2026-08-11T00:30 に固定する。このときの UTC 換算は
    # 2026-08-10T15:30 なので、もし判定が JST ではなく UTC やホストのローカル日付
    # （例えば UTC で動くCIサーバー）に引きずられていたら、この2件の当落は逆転する。
    _freeze_now(monkeypatch, datetime(2026, 8, 11, 0, 30, tzinfo=unpublish.JST))

    path = _published(tmp_path, {
        # JST では既に 8/11（今日）。UTC 基準で誤判定すると「まだ8/10」として
        # 落とされてしまう組み合わせ
        "a": {"youtube_video_id": "vid_jst_today_early",
              "publish_at": "2026-08-11T00:15:00+09:00"},
        # JST ではまだ 8/10（昨日）。文字列前方一致の旧ロジックだと
        # ホストのローカル日付次第で誤って「今日」に含めてしまいかねない組み合わせ
        "b": {"youtube_video_id": "vid_jst_yesterday_late",
              "publish_at": "2026-08-10T23:45:00+09:00"},
        # タイムゾーン無しの値。このパイプラインでは常にJST運用なのでJSTとして扱う
        "c": {"youtube_video_id": "vid_naive_treated_as_jst_today",
              "publish_at": "2026-08-11T05:00:00"},
    })
    monkeypatch.setattr(unpublish, "PUBLISHED", path)

    ids = unpublish._today_ids()

    assert set(ids) == {"vid_jst_today_early", "vid_naive_treated_as_jst_today"}


def test_publish_atがパース不能なら警告して対象から除外する(tmp_path, monkeypatch, capsys):
    _freeze_now(monkeypatch, datetime(2026, 8, 11, 12, 0, tzinfo=unpublish.JST))

    path = _published(tmp_path, {
        "a": {"youtube_video_id": "vid_broken", "publish_at": "not-a-valid-datetime"},
        "b": {"youtube_video_id": "vid_ok", "publish_at": "2026-08-11T07:30:00+09:00"},
    })
    monkeypatch.setattr(unpublish, "PUBLISHED", path)

    ids = unpublish._today_ids()

    # 壊れた値は対象から外れるが、黙って消えるのではなく警告が出て、
    # 正常な値の判定は影響を受けない
    assert ids == ["vid_ok"]
    out = capsys.readouterr().out
    assert "vid_broken" in out
    assert "パースできません" in out


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
