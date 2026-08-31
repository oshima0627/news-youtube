# TikTok 投稿（1分超バリアント）設計

2026-08-30。ショートと同じ一次資料から、TikTok 用に **70〜80秒**の別バリアントを作り、
YouTube の枠と同じ時刻に Direct Post API で投稿する。

## なぜ1分超なのか

TikTok の Creator Rewards Program は **60秒以上の動画だけ**が対象で、これが最も多い
失格理由。他にフォロワー1万人・直近30日で10万再生・個人アカウント（Business 不可）が要る。
つまり収益化そのものは当面届かない。**それでも最初から60秒を超えておく**のは、
後から遡って尺を伸ばせないため。59秒で出した本数はすべて永久に対象外になる。

## 尺と台本

| | YouTube（既存） | TikTok（追加） |
|---|---|---|
| ナレーション | 330〜355字 | **410〜450字** |
| 尺の窓 | 56〜61秒 | **70〜80秒** |
| 一次資料 | — | **同じ**（`source_url` 一致を強制） |
| 引用カード・画像・出典 | — | 同じ |

410字 × 0.171秒/字 = 70.1秒、450字 = 77.0秒。長尺の1章
（`SEGMENT_MIN_CHARS` / `SEGMENT_MAX_CHARS`、`SEGMENT_TARGET_MIN` / `SEGMENT_TARGET_MAX`）と
同じ幅なので、**新しい尺の定義は作らず既存の定数を再利用する**。判定基準を2箇所に置かない。

台本は人が書く（`--script` と同じ理由。`ANTHROPIC_API_KEY` が無い）。
`run_daily.py --tiktok-script <path>` を足し、`--script` と同じ検証
（`source_url` が `evidence.collect()` の選んだ一次資料と一致すること）を通す。
省略すれば TikTok バリアントは作られず、現在の挙動のまま。

## 生成物

```
work/<id>/            YouTube 用（59秒）。いまのまま
work/<id>/tiktok/     追加。script.json / voice.wav / video.mp4 / frames/ / meta.json
```

`photo.jpg` / `license.json` / `recipes/<id>.json` は共有する。同じ題材・同じ一次資料を
二重に持たない。

## 投稿タイミング

TikTok の Direct Post API に `schedule_time` に相当するフィールドは無い。投稿した瞬間に出る。
作り置き運用（`--days-ahead 3〜5`）と噛み合わないので、**キューと定時タスクに分ける**。

```
run_daily.py → YouTube の --schedule が通った後 → state/tiktok_queue.json に {workdir, due}
schtasks（07:25 / 18:25）→ post_tiktok_due.py → due を過ぎた未投稿を投げる
```

`run_daily.py` は TikTok API を触らない。TikTok 側が落ちても YouTube の予約は無傷。
定時タスクは `ANTHROPIC_API_KEY` も VOICEVOX も要らないので無人で回る。

投稿済みの workdir は消さない（キューが `video.mp4` を参照する）。消えていたら黙って
飛ばさず、原因を出して落とす。

## 関門（`upload_tiktok.post()` の中に1箇所ずつ。全経路がここを通る）

1. **尺の下限** — mp4 の実尺が `TIKTOK_MIN_SECONDS`（61.0秒）未満なら投稿しない。
   60秒を割った動画は Creator Rewards の対象外で、成功ログだけが出て価値がゼロになる。
2. **公開範囲ガード** — `creator_info/query` の `privacy_level_options` に
   `PUBLIC_TO_EVERYONE` が無ければ投稿しない。`--allow-self-only` を明示した
   ときだけ SELF_ONLY で通す（審査前の経路確認用）。

   **2026-08-31 追記（実測により当初の想定を訂正）**: この関門は**審査状態も
   投稿の可否も判定していない**。Sandbox の `creator_info` は
   PUBLIC_TO_EVERYONE を含む3つを返したが、`PUBLIC_TO_EVERYONE` でも
   `SELF_ONLY` でも投稿は HTTP 403
   `unaudited_client_can_only_post_to_private_accounts` で拒否された。

   エラーが指すのは投稿の公開範囲ではなく **TikTok アカウントの設定**。
   ガイドライン: "All user accounts using the API client to post must be set to
   private at the time of posting."。審査前の投稿には次の制約がある:

   - **アカウントを非公開に設定していること**
   - 24時間で5ユーザーまで
   - 内容は SELF_ONLY のみ

   当初の前提「未審査の投稿は SELF_ONLY に強制される（APIは成功を返す）」は
   誤り。**実際は拒否される**ので、誰にも届かない動画が成功ログ付きで積み上がる
   事故は起きない。
3. **アカウント取り違えガード** — `meta.json` の `expected_tiktok_open_id` と
   認証中の open_id が一致しなければ投稿しない（YouTube の `expected_channel_id` と同型）。

## 投稿の成否

Direct Post は非同期。`init` が 200 を返しても後で失敗しうる。`publish_id` を受けたあと
`post/publish/status/fetch/` を `PUBLISH_COMPLETE` までポーリングし、確認できてから
`state/tiktok_posted.json` に記録する。init の 200 だけで成功と書かない。

## キャプション

`build_caption(meta) -> str` の純関数1つ。`title` ＋ 出典1行（会議名・日付・発言者）＋
`tags` からのハッシュタグ。上限 2200 UTF-16 runes をテストで縛る。モデルには書かせない。

## 認証

OAuth v2 + PKCE。`tiktok_client.json`（`client_key` / `client_secret`）を読み、
`tiktok_token.json` にトークンを保存する。アクセストークンは24時間、リフレッシュトークンは
365日。期限切れは自動でリフレッシュする。両ファイルとも `.gitignore` に入れる。

## 状態

`state/published.json` には触らない。あれは YouTube の重複投稿・二重予約の防止だけを
担っている。TikTok は別ファイル（`tiktok_queue.json` / `tiktok_posted.json`）に持つ。

## 未確認

- **Content Posting API が個人アカウントで使えるか。** Business アカウント必須だと
  Creator Rewards（個人アカウント必須）と両立しない。
- 審査の所要期間。

## やらないこと

- 長尺（16:9）は対象外。YouTube 側で0再生であり、横展開の価値が測れていない
- 過去198本の遡り投稿はしない
- TikTok 用に画面レイアウトを変えない。テロップ枚数は尺に応じて自動で増える。
  維持率を測ってから考える
