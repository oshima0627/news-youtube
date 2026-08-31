#!/usr/bin/env python3
"""ビルドした TikTok バリアントを TikTok に投稿する。

  python scripts/upload_tiktok.py --auth-only            # 初回の認証と審査状態の確認
  python scripts/upload_tiktok.py work/<id>/tiktok       # 1本投稿する
  python scripts/upload_tiktok.py work/<id>/tiktok --allow-self-only

`upload_youtube.py` と同じ形にしてある。**投稿を止める判断はすべて post() の
中にある**（CLAUDE.md「関門は1つにして、全経路がそれを通る」）。定時タスク
（post_tiktok_due.py）も同じ post() を呼ぶので迂回できない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import tiktok                                  # noqa: E402
from scripts.build_short import mp4_duration_seconds        # noqa: E402


def post(api, workdir: Path, *, allow_self_only: bool = False,
         state_dir: Path | None = None) -> dict:
    """1本を TikTok に投稿する。関門を全部ここで通す。

    判定の順序は「安いものから」。重複と尺はローカルで判るので最初に見る
    ——既に出した動画や60秒に届かない動画のために、通信も数MBの
    アップロードもしない。

    投稿の完了は `await_complete` で確認してから返す。Direct Post は非同期で、
    init が 200 を返しても後段で失敗しうる。init の成功だけを記録すると、
    失敗した投稿が「済み」になって二度と出せなくなる。

    **重複投稿の関門はここに置く。** 以前はキューのフィルタ
    （tiktok_queue.due_entries）にだけあり、このCLIを直接叩く経路が
    素通りしていた。CLAUDE.md が名指ししている「run_daily にだけ検証を置いて
    手動CLIが素通りした」のとまったく同じ穴だった。
    """
    from scripts import tiktok_queue

    workdir = Path(workdir)
    state_dir = Path(state_dir) if state_dir is not None else ROOT / "state"

    posted = tiktok_queue.load_posted(state_dir)
    already = posted.get(Path(workdir).as_posix())
    if already:
        raise tiktok.AlreadyPosted(
            f"{workdir} は投稿済みです"
            f"（publish_id={already.get('publish_id')}）。"
            "同じ動画を2本 TikTok に並べないため投稿しません。"
            "作り直したいなら新しい題材でバリアントを作ってください")

    video = workdir / "video.mp4"
    meta_path = workdir / "meta.json"
    if not video.exists():
        raise tiktok.TikTokError(
            f"{video} がありません。先に build_short.py で TikTok バリアントを"
            "作ってください")
    if not meta_path.exists():
        raise tiktok.TikTokError(f"{meta_path} がありません")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # 1. 尺。ここだけは通信なしで判る
    duration = mp4_duration_seconds(video)
    tiktok.assert_over_a_minute(duration)

    # 2. アカウント取り違え
    tiktok.assert_expected_account(api.open_id(), meta)

    # 3. 審査状態とアカウント側の尺の上限
    info = api.creator_info()
    tiktok.assert_duration_allowed(duration, info)
    privacy_level = tiktok.resolve_privacy_level(
        info, allow_self_only=allow_self_only)

    caption = tiktok.build_caption(meta)
    publish_id = api.publish(video=video, caption=caption,
                             privacy_level=privacy_level)
    result = api.await_complete(publish_id)
    return {
        "publish_id": publish_id,
        "privacy_level": privacy_level,
        "duration": duration,
        "title": meta.get("title"),
        "source_url": meta.get("source_url"),
        "status": result.get("status"),
    }


def die(msg: str, code: int = 1) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path, nargs="?",
                    help="work/<id>/tiktok。--auth-only のときは省略できる")
    ap.add_argument("--auth-only", action="store_true",
                    help="認証だけ通して tiktok_token.json を作り、審査状態を表示する")
    ap.add_argument("--allow-self-only", action="store_true",
                    help="審査前でも SELF_ONLY で投稿する（経路の確認用）。"
                         "この動画は誰にも見えない")
    a = ap.parse_args()

    from scripts.tiktok_api import TikTokApi, TikTokAuthError, authorize

    # --auth-only はトークンがまだ無いときに作るための入口。ここで
    # from_files をそのまま呼ぶと「token.json がありません → --auth-only を
    # 実行してください」と自分自身を案内する堂々巡りになる。
    if a.auth_only and not (ROOT / "tiktok_token.json").exists():
        try:
            authorize(ROOT)
        except TikTokAuthError as e:
            die(str(e))

    try:
        api = TikTokApi.from_files(ROOT)
    except TikTokAuthError as e:
        die(str(e))

    if a.auth_only:
        from scripts.tiktok_api import is_sandbox_key

        info = api.creator_info()
        options = info.get("privacy_level_options") or []
        sandbox = is_sandbox_key(api.client.get("client_key"))
        print(f"✓ 認証しました: @{info.get('creator_username')}"
              f"（open_id={api.open_id()}）")
        print(f"- 使っている鍵: {'Sandbox' if sandbox else 'Production'}")
        print(f"- 選べる公開範囲: {options}")
        if "PUBLIC_TO_EVERYONE" in options:
            print("✓ このクライアントは公開投稿を選べます")
            if sandbox:
                # Sandbox は審査に関係なく公開範囲を返す。ここを「審査が下りた」と
                # 読むと、Production が Draft のままなのに本番運用へ進んでしまう。
                print("! ただしこれは Sandbox の鍵です。**Production の審査状況は"
                      "これでは分かりません。**本番投稿の前に "
                      "tiktok_client.json を Production の鍵に差し替えて"
                      "もう一度確認してください")
        else:
            print("! 公開投稿（PUBLIC_TO_EVERYONE）が選べません。"
                  "video.publish の審査が未了だと、投稿しても"
                  "すべて自分だけ表示になります")
        return

    if not a.workdir:
        die("workdir を指定してください")

    from scripts import tiktok_queue

    try:
        result = post(api, a.workdir, allow_self_only=a.allow_self_only)
    except tiktok.TikTokError as e:
        die(str(e), code=getattr(e, "exit_code", 1))

    tiktok_queue.mark_posted(ROOT / "state", str(a.workdir), result)
    print(f"✓ 投稿しました: publish_id={result['publish_id']} "
          f"({result['privacy_level']}, {result['duration']:.2f}秒)")


if __name__ == "__main__":
    main()
