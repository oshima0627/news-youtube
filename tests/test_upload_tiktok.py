"""投稿経路（upload_tiktok.post）の単体テスト。

3つの関門が**全部**この関数を通ることを縛る。関門そのものの判定は
test_tiktok.py にあるので、ここで見るのは「呼ばれる順序」と
「止まったときに外部へ何も送っていないこと」。

止め損なったときの損失が大きい順に、安い判定から先に置く:
  尺（ローカルで測れる）→ アカウント → 審査状態 → 送信
"""

from __future__ import annotations

import json

import pytest

from scripts import tiktok
from scripts import upload_tiktok as ut


class FakeApi:
    """呼ばれた順に記録するだけの API。実際の HTTP は投げない。"""

    def __init__(self, *, open_id="open-abc",
                 privacy_options=("PUBLIC_TO_EVERYONE", "SELF_ONLY"),
                 max_duration=600, final_status="PUBLISH_COMPLETE"):
        self._open_id = open_id
        self._privacy_options = list(privacy_options)
        self._max_duration = max_duration
        self._final_status = final_status
        self.calls: list[str] = []
        self.posted: dict | None = None

    def open_id(self):
        self.calls.append("open_id")
        return self._open_id

    def creator_info(self):
        self.calls.append("creator_info")
        return {"privacy_level_options": self._privacy_options,
                "max_video_post_duration_sec": self._max_duration,
                "creator_username": "tester"}

    def publish(self, *, video, caption, privacy_level):
        self.calls.append("publish")
        self.posted = {"video": video, "caption": caption,
                       "privacy_level": privacy_level}
        return "publish-1"

    def await_complete(self, publish_id):
        self.calls.append("await_complete")
        if self._final_status != "PUBLISH_COMPLETE":
            raise tiktok.TikTokError(f"投稿が完了しませんでした: {self._final_status}")
        return {"status": self._final_status, "publish_id": publish_id}


@pytest.fixture
def workdir(tmp_path):
    d = tmp_path / "abc123" / "tiktok"
    d.mkdir(parents=True)
    (d / "video.mp4").write_bytes(b"not really an mp4")
    (d / "meta.json").write_text(json.dumps({
        "id": "abc123",
        "title": "出生数67万人・出生率1.14",
        "tags": ["少子化", "国会"],
        "source_url": "https://kokkai.ndl.go.jp/txt/122105254X02320260604/16",
        "source_context": "第221回国会 衆議院本会議 2026-06-04 高山聡史",
        "expected_tiktok_open_id": "open-abc",
    }, ensure_ascii=False), encoding="utf-8")
    return d


@pytest.fixture
def long_enough(monkeypatch):
    monkeypatch.setattr(ut, "mp4_duration_seconds", lambda p: 74.2)


def test_すべて通れば投稿して結果を返す(workdir, long_enough):
    api = FakeApi()
    result = ut.post(api, workdir)
    assert result["publish_id"] == "publish-1"
    assert result["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert result["duration"] == pytest.approx(74.2)


def test_投稿の完了を確認してから返す(workdir, long_enough):
    api = FakeApi()
    ut.post(api, workdir)
    assert api.calls[-1] == "await_complete"


def test_完了が確認できなければ例外にする(workdir, long_enough):
    api = FakeApi(final_status="FAILED")
    with pytest.raises(tiktok.TikTokError):
        ut.post(api, workdir)


def test_キャプションと公開範囲を渡す(workdir, long_enough):
    api = FakeApi()
    ut.post(api, workdir)
    assert "出生数67万人" in api.posted["caption"]
    assert "#少子化" in api.posted["caption"]
    assert api.posted["privacy_level"] == "PUBLIC_TO_EVERYONE"


def test_60秒以下なら投稿しない(workdir, monkeypatch):
    monkeypatch.setattr(ut, "mp4_duration_seconds", lambda p: 58.4)
    api = FakeApi()
    with pytest.raises(tiktok.VideoTooShort):
        ut.post(api, workdir)


def test_60秒以下のときはAPIを一度も呼ばない(workdir, monkeypatch):
    """尺はローカルで測れる。届かない動画のために通信もアップロードもしない。"""
    monkeypatch.setattr(ut, "mp4_duration_seconds", lambda p: 58.4)
    api = FakeApi()
    with pytest.raises(tiktok.VideoTooShort):
        ut.post(api, workdir)
    assert api.calls == []


def test_アカウントが違えば投稿しない(workdir, long_enough):
    api = FakeApi(open_id="open-someone-else")
    with pytest.raises(tiktok.AccountMismatch):
        ut.post(api, workdir)
    assert "publish" not in api.calls


def test_未審査なら投稿しない(workdir, long_enough):
    api = FakeApi(privacy_options=("SELF_ONLY",))
    with pytest.raises(tiktok.NotAudited):
        ut.post(api, workdir)
    assert "publish" not in api.calls


def test_未審査でもallow_self_onlyなら投稿する(workdir, long_enough):
    api = FakeApi(privacy_options=("SELF_ONLY",))
    result = ut.post(api, workdir, allow_self_only=True)
    assert result["privacy_level"] == "SELF_ONLY"


def test_アカウントの投稿上限を超えていれば投稿しない(workdir, long_enough):
    api = FakeApi(max_duration=60)
    with pytest.raises(tiktok.VideoTooLong):
        ut.post(api, workdir)
    assert "publish" not in api.calls


def test_動画が無ければ原因を出して止まる(workdir, long_enough):
    (workdir / "video.mp4").unlink()
    api = FakeApi()
    with pytest.raises(tiktok.TikTokError) as e:
        ut.post(api, workdir)
    assert "video.mp4" in str(e.value)
    assert api.calls == []


def test_metaが無ければ原因を出して止まる(workdir, long_enough):
    (workdir / "meta.json").unlink()
    api = FakeApi()
    with pytest.raises(tiktok.TikTokError) as e:
        ut.post(api, workdir)
    assert "meta.json" in str(e.value)


# ── 重複投稿の関門は post() の中に置く ─────────────────────────
#
# キューのフィルタ（tiktok_queue.due_entries）にだけ置いていたため、
# upload_tiktok.py を直接叩く経路が素通りしていた。CLAUDE.md が名指しで
# 警告している「同型の穴」（run_daily にだけ検証を置いて手動CLIが素通り）
# とまったく同じ形。**全経路が通る post() の中に移す。**

def test_投稿済みのworkdirは投稿しない(workdir, long_enough, tmp_path):
    from scripts import tiktok_queue

    api = FakeApi()
    ut.post(api, workdir, state_dir=tmp_path)
    tiktok_queue.mark_posted(tmp_path, str(workdir), {"publish_id": "p1"})

    api2 = FakeApi()
    with pytest.raises(tiktok.AlreadyPosted):
        ut.post(api2, workdir, state_dir=tmp_path)


def test_投稿済みなら外部へ何も送らない(workdir, long_enough, tmp_path):
    from scripts import tiktok_queue

    tiktok_queue.mark_posted(tmp_path, str(workdir), {"publish_id": "p1"})
    api = FakeApi()
    with pytest.raises(tiktok.AlreadyPosted):
        ut.post(api, workdir, state_dir=tmp_path)
    assert api.calls == []


def test_区切り文字が違っても投稿済みと判定する(workdir, long_enough, tmp_path):
    from scripts import tiktok_queue

    tiktok_queue.mark_posted(tmp_path, str(workdir).replace(chr(92), "/"),
                             {"publish_id": "p1"})
    with pytest.raises(tiktok.AlreadyPosted):
        ut.post(FakeApi(), workdir, state_dir=tmp_path)


def test_投稿済みでなければ通常どおり投稿する(workdir, long_enough, tmp_path):
    assert ut.post(FakeApi(), workdir, state_dir=tmp_path)["publish_id"] == "publish-1"


def test_メッセージに投稿済みのpublish_idが出る(workdir, long_enough, tmp_path):
    from scripts import tiktok_queue

    tiktok_queue.mark_posted(tmp_path, str(workdir), {"publish_id": "p-old"})
    with pytest.raises(tiktok.AlreadyPosted) as e:
        ut.post(FakeApi(), workdir, state_dir=tmp_path)
    assert "p-old" in str(e.value)
