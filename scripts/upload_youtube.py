#!/usr/bin/env python3
"""ビルドしたショートを YouTube に上げる。

  python scripts/upload_youtube.py --auth-only                      # 初回の認証だけ
  python scripts/upload_youtube.py work/<id>                        # private で投稿
  python scripts/upload_youtube.py work/<id> --schedule 2026-08-11T07:30:00+09:00

tora-kirinuki/scripts/upload_youtube.py から移植した。
チャンネル取り違えのガードと予約公開はそのまま持ってきている。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # python scripts/X.py 形式で起動できるようにする

CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN = ROOT / "token.json"
PUBLISHED = ROOT / "state" / "published.json"

# 必要なスコープは4つの要件から決まる。
#
#   videos.insert    → youtube.upload
#   channels.list    → youtube.readonly
#                      ブランドアカウントを持つと同意画面はアカウントを選ぶだけで、
#                      API は既定チャンネルに上げる。実際に一度、意図しない
#                      チャンネルに入った。事前確認の手段が無いとこの事故は静かに続く。
#   videos.update    → youtube.force-ssl（公開設定の変更に必要。狭いスコープが無い）
#   reports.query    → yt-analytics.readonly（インプレッション数・トラフィックソースの確認用）
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def get_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        die("依存が足りません。"
            "`pip install google-api-python-client google-auth-oauthlib`")

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not CLIENT_SECRET.exists():
            die(f"{CLIENT_SECRET.name} がありません。\n"
                "  Google Cloud で YouTube Data API v3 を有効化し、\n"
                "  OAuth クライアント（デスクトップアプリ）を作成して配置してください。")
        # 初回のみブラウザが開く。以降は token.json の refresh_token で無人化される
        creds = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET), SCOPES).run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
        print(f"✓ 認証情報を保存しました: {TOKEN.name}（コミットしないこと）")

    return build("youtube", "v3", credentials=creds)


def current_channel(service) -> dict | None:
    """いま認証しているトークンがどのチャンネルに紐づくかを返す。"""
    from googleapiclient.errors import HttpError
    try:
        items = service.channels().list(
            part="snippet", mine=True).execute().get("items", [])
    except HttpError as e:
        print(f"! チャンネルを確認できませんでした: {e}")
        return None
    return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]} if items else None


def assert_expected_channel(service, meta: dict) -> dict | None:
    """meta の expected_channel_id と一致しない限りアップロードしない。

    間違ったチャンネルに上げると消して上げ直すことになる。上げる前に止めるほうが安い。
    """
    ch = current_channel(service)
    expected = meta.get("expected_channel_id")
    if not expected:
        die("meta.json に expected_channel_id がありません。"
            "取り違えを防げないのでアップロードしません")
    if ch is None or ch["id"] != expected:
        got = f"{ch['title']}（{ch['id']}）" if ch else "取得できず"
        die("アップロード先のチャンネルが指定と一致しません。\n"
            f"  期待: {expected}\n"
            f"  実際: {got}\n"
            f"  {TOKEN.name} を削除し、同意画面で正しいチャンネルを選び直してください。")
    return ch


def upload(service, workdir: Path, meta: dict, description: str, privacy: str) -> str:
    from googleapiclient.http import MediaFileUpload

    video = workdir / "video.mp4"
    if not video.exists():
        die(f"{video} がありません。先に build_short.py を実行してください")

    # 言語は必ず明示する。省略すると YouTube が推測し、BGMチャンネルでは
    # 日本語の動画9本中8本が en と判定された
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": description[:5000],
            "tags": meta.get("tags", []),
            "categoryId": meta.get("category_id", "22"),
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }

    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    request = service.videos().insert(part="snippet,status", body=body,
                                      media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  アップロード {int(status.progress() * 100)}%")
    return response["id"]


def set_privacy(service, video_id: str, privacy: str, publish_at: str | None = None) -> None:
    """公開設定を変更する。

    videos.update は部分更新ではなく part を丸ごと置き換える。status だけを渡すと
    selfDeclaredMadeForKids などが既定値に戻る恐れがあるため、現在の status を
    読んでから必要な項目だけ差し替えて送る。

    publish_at を渡すと即座には公開せず、YouTube 側の予約公開に乗せる。
    このとき privacyStatus は "private" のまま送る（"public" と同時に送ると
    無視されて即時公開になる）。指定時刻になると YouTube が自動で public に切り替える。
    """
    items = service.videos().list(part="status", id=video_id).execute().get("items", [])
    if not items:
        die(f"動画が見つかりません: {video_id}")
    cur = items[0]["status"]
    # update で送れるのはこの範囲だけ。uploadStatus / madeForKids などは
    # 読み取り専用で、そのまま送り返すとエラーになる
    writable = ("license", "embeddable", "publicStatsViewable",
                "selfDeclaredMadeForKids")
    status = {k: cur[k] for k in writable if k in cur}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    else:
        status["privacyStatus"] = privacy
    service.videos().update(part="status",
                            body={"id": video_id, "status": status}).execute()


def load_published() -> dict:
    """state/published.json を読む。無言で落ちると事故調査ができないので、
    不在・壊れているときは原因つきで止める（unpublish.py と同じ配慮）。"""
    if not PUBLISHED.exists():
        die(f"{PUBLISHED} がありません。先に python scripts/upload_youtube.py "
            "work/<id> でアップロードしてください")
    try:
        return json.loads(PUBLISHED.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        die(f"{PUBLISHED} が壊れています（JSONとして読めません）: {e}")


def record(meta: dict, video_id: str, privacy: str, ch: dict | None,
           publish_at: str | None = None) -> None:
    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    data = (json.loads(PUBLISHED.read_text(encoding="utf-8-sig"))
            if PUBLISHED.exists() else {"videos": {}})
    entry = {
        "youtube_video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": meta["title"],
        "privacy_status": privacy,
        # どのチャンネルに上がったかを必ず残す。追跡できないと取り違えに気づけない
        "channel_id": (ch or {}).get("id"),
        "channel_title": (ch or {}).get("title"),
        "source_url": meta.get("source_url"),
    }
    if publish_at:
        entry["publish_at"] = publish_at
    data["videos"][meta["id"]] = entry
    PUBLISHED.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path, nargs="?",
                    help="--auth-only のときは省略できる")
    ap.add_argument("--auth-only", action="store_true",
                    help="認証だけ通して token.json を作る")
    ap.add_argument("--publish", action="store_true",
                    help="アップロード済みの動画を公開に切り替える")
    ap.add_argument("--schedule", metavar="ISO8601",
                    help="即時公開せず、指定時刻に自動公開する予約を入れる"
                         "（例: 2026-08-11T03:00:00Z。JSTなら+09:00を付ける）")
    a = ap.parse_args()

    service = get_service()
    if a.auth_only:
        ch = current_channel(service)
        print(f"✓ 認証しました: {ch['title']}（{ch['id']}）" if ch else "✓ 認証しました")
        return
    if not a.workdir:
        die("workdir を指定してください")

    meta = json.loads((a.workdir / "meta.json").read_text(encoding="utf-8"))
    ch = assert_expected_channel(service, meta)
    print(f"- チャンネル: {ch['title']}（{ch['id']}）")

    if a.publish or a.schedule:
        data = load_published()
        entry = data["videos"].get(meta["id"]) or die(
            f"{meta['id']} はまだアップロードされていません")
        if a.schedule:
            set_privacy(service, entry["youtube_video_id"], "private", publish_at=a.schedule)
            entry["privacy_status"] = "private"
            entry["publish_at"] = a.schedule
            PUBLISHED.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"✓ 予約しました: {entry['url']}  → {a.schedule} に自動公開")
        else:
            set_privacy(service, entry["youtube_video_id"], "public")
            entry["privacy_status"] = "public"
            PUBLISHED.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"✓ 公開しました: {entry['url']}")
        return

    description = (a.workdir / "description.txt").read_text(encoding="utf-8")
    privacy = meta.get("privacy_status", "private")
    vid = upload(service, a.workdir, meta, description, privacy)
    record(meta, vid, privacy, ch)
    print(f"✓ https://www.youtube.com/watch?v={vid}  ({privacy})")
    print("  内容を確認してから --publish または --schedule で公開してください")


if __name__ == "__main__":
    main()
