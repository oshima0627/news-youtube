# HANDOFF

最終更新: 2026-08-30（セッション: TikTok 投稿の実装。1分超バリアントを作る経路を通した）

## いま何をしているのか

**TikTok にも投稿できるようにした。** ショートと同じ一次資料・同じ引用から、
本文だけを長く書いた **70〜80秒版**を `work/<id>/tiktok/` に作り、YouTube の枠と
同じ時刻に Direct Post API で投稿する。

コードとテストは完成して全経路を通した。**ただし実投稿はまだ1本もしていない。**
このPCに TikTok の認証情報が無く、`video.publish` の審査も出していないため
（下記「次にやること」の1〜2）。

前セッションからの状況は変わっていない: **枠は 2026-09-01 18:30 JST まで埋まっている
（予約11本）。次の空きは 9/2 07:30。** `ANTHROPIC_API_KEY` は無いので、台本は
対話セッションが書いて `--script` で渡す運用のまま。

## 今回やったこと

### 1. TikTok 投稿の一式を実装した（TDD、新規104テスト）

| ファイル | 役割 |
|---|---|
| `scripts/tiktok.py` | **投稿を止める判断だけ**を集めた。3つの関門と純関数 |
| `scripts/tiktok_api.py` | HTTP クライアント。OAuth(PKCE)・init・アップロード・完了確認 |
| `scripts/upload_tiktok.py` | 投稿CLI。`post()` に全経路が入る |
| `scripts/post_tiktok_due.py` | 定時タスクの入口。枠が来たものを投げる |
| `scripts/tiktok_queue.py` | `state/tiktok_queue.json` / `tiktok_posted.json` |

既存への変更（**既定の引数は現在の挙動そのままで、既存の呼び出しは変わらない**）:

- `scripts/build_short.py`: `resolve_sources()` を切り出し、`build()` に
  `assets_dir` / `recipe_id` / `target_min` / `target_max` を追加
- `scripts/script_writer.py`: `TIKTOK_MIN_CHARS=410` / `TIKTOK_MAX_CHARS=450` と
  `load_tiktok_script()`（`load_script` を呼ぶので source_url の検証は共通）
- `scripts/run_daily.py`: `--tiktok-script`、`parse_args()` の切り出し、
  `write_tiktok_meta()` / `build_tiktok_variant()` / `try_build_tiktok_variant()`
- `CLAUDE.md`、`.gitignore`（`tiktok_client.json` / `tiktok_token.json`）
- 仕様書: `docs/superpowers/specs/2026-08-30-tiktok-posting-design.md`

### 2. 実際に動画を1本作って、投稿経路を最後まで通した

```bash
python scripts/run_daily.py --keyword "医師偏在指標 新潟" \
  --script <短尺台本.json> --tiktok-script <TikTok台本.json> \
  --dry-run --days-ahead 3 --limit 1
```

## 検証済みの事実（実際に画面に出した出力）

- **`pytest` 539 passed**（前回 435 → 今回 +104）。警告なし。
- **同じ題材から2本ビルドできた**（`work/1d04e9d8cd04/`）:

  ```
  試行1: speedScale=0.945 → 実尺58.67秒（許容範囲内）
    尺: voice.wav 58.67秒 → video.mp4 58.67秒（差 +0.00秒）  テロップ22枚
  試行1: speedScale=0.949 → 実尺74.14秒（許容範囲内）
    尺: voice.wav 74.14秒 → video.mp4 74.17秒（差 +0.02秒）  テロップ28枚
  ```

  **TikTok版は 74.17秒。** ffprobe で実測し、`tiktok.assert_over_a_minute` を
  通過することを確認した。
- **投稿経路を実物で最後まで通した**（送信先の API だけ差し替え。それ以外＝
  尺の測定・3つの関門・キャプション生成・完了確認・キューの記録は本番と同じコード）:

  ```
  publish_id: publish-sim-1 / privacy_level: PUBLIC_TO_EVERYONE
  duration: 74.166667 / status: PUBLISH_COMPLETE
  source_info: {"video_size": 3036922, "chunk_size": 3036922, "total_chunk_count": 1}
  キュー: 枠前(07:00)→[] / 枠後(07:30)→[work/1d04e9d8cd04/tiktok] / 投稿後→[]
  ```

- **キャプションは 153 runes**（上限2200）。中身:

  ```
  新潟県は医師偏在指標で全国第四十四位 参院決算委で問われた医師不足

  根拠: 第221回国会 参議院決算委員会 2026-07-06 小林一大
  https://kokkai.ndl.go.jp/txt/122114103X00920260706/35

  #医師不足 #医師偏在 #地域医療 #新潟県 #国会
  ```

- **画面を目視で確認した**（`stage.png` と `frames/002.png`）。被写体は
  小林一大本人（防衛省 / CC BY 4.0）で発言者と一致。引用カードは
  「医師偏在指標で全国第44位」で逐語引用の部分文字列。
- **テロップのはみ出しは実質なし。** 両版とも最大右端 1054px で、画面幅 1080px の
  **内側**（許容線 1016px は超えるが、`。` が余白に入るだけで文字は切れていない）。
  目視でも確認済み。
- **TikTok API の仕様を実際のドキュメントで確認した**:
  - 未審査クライアントの投稿は全て SELF_ONLY に強制される
  - Direct Post に `schedule_time` 相当のフィールドは**無い**
  - キャプション上限 2200 UTF-16 runes、`creator_info/query` を先に呼ぶ必要あり
  - PKCE の `code_challenge` は **hex エンコードの SHA256**（base64url ではない）
  - アクセストークン24時間 / リフレッシュトークン365日
  - Creator Rewards: 60秒以上・フォロワー1万人・直近30日10万再生・個人アカウント

## 未検証のもの

- **TikTok に1本も投稿していない。** 認証情報（`tiktok_client.json`）が無く、
  `video.publish` の審査も出していない。HTTP を実際に投げる部分
  （`tiktok_api.TikTokApi` の `creator_info` / `publish` / `_fetch_status` と
  `authorize()` の OAuth 往復）は**一度も本物のサーバに当たっていない**。
- **Content Posting API が個人アカウントで使えるかは未確認。** Business
  アカウント必須だと Creator Rewards（個人アカウント必須）と両立しない。
  **審査を出す前にここを確かめること。**
- **`work/1d04e9d8cd04/tiktok/meta.json` の `expected_tiktok_open_id` は空。**
  認証前に作ったため。**このバリアントはこのままでは投稿できない**
  （アカウント取り違えガードが弾く）。認証後に作り直すこと。
- 今回の題材（医師偏在）は YouTube にも投稿していない（`--dry-run`）。
  枠に載せるなら作り直しになる。
- 定時タスク（schtasks）はまだ登録していない。

## 次にやること

1. **TikTok 開発者アプリを作る**（人にしかできない）。
   - TikTok for Developers でアプリ登録 → Content Posting API を追加 →
     Direct Post を有効化
   - **プライバシーポリシーと利用規約の公開URL**を用意する（審査に必須）
   - リダイレクトURI に `http://localhost:8723/callback` を登録する
     （`tiktok_api.authorize` の既定。**文字列が一致しないと同意画面で落ちる**）
   - `client_key` / `client_secret` をリポジトリ直下の `tiktok_client.json` に置く
     （`.gitignore` 済み。コミットしないこと）

2. **認証して、審査状態を見る**:

   ```bash
   python scripts/upload_tiktok.py --auth-only
   ```

   `選べる公開範囲` に `PUBLIC_TO_EVERYONE` が出れば審査済み。出なければ
   `video.publish` の審査を申請する。**審査が下りるまで実投稿はしない**
   （投稿しても全部 SELF_ONLY になる）。

3. **審査が下りたら、1本作って投稿する**:

   ```bash
   python scripts/run_daily.py --keyword "<2語以上>" \
     --script <短尺台本.json> --tiktok-script <TikTok台本.json> \
     --days-ahead <N> --limit 1
   python scripts/post_tiktok_due.py --dry-run    # キューを確認
   ```

   TikTok台本は **410〜450字**（`load_tiktok_script` が範囲外を拒否する）。
   短尺は従来どおり330〜355字。`source_url` は両方に必須で、一致しないと中止。

4. **定時タスクを登録する**（枠の時刻に実際に投げる）:

   ```
   schtasks /create /tn "tiktok-0725" /sc daily /st 07:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   schtasks /create /tn "tiktok-1825" /sc daily /st 18:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   ```

5. **9/2 以降の YouTube の枠を埋める**（空きは 9/2 07:30 から）。手順は従来どおり。
   実測済みで未使用の検索語: `医師偏在指標 新潟`（今回書いた台本2本がそのまま使える。
   scratchpad に置いたので消える。必要なら書き直す）、`外国人 土地`。

6. **8/30 18:30 に `8zGOoD1GhUQ` が公開されたか見る**（`--script` 経路の初公開）。

7. **8/31 以降に `myjKRuLTmXw`（教員不足）の再生数を他の回と比べる**
   （自殺者数に触れているため配信制限の可能性。他の回は約1,200）。

## 触ってはいけないところ

- **`tiktok.TIKTOK_MIN_SECONDS`（61.0秒）を下げない。** 60秒を割った動画は
  Creator Rewards の対象外で、投稿は通るので成功ログだけが積み上がる。
- **未審査ガードを外さない。** `--allow-self-only` は経路確認専用。常用すると
  誰にも見えない動画を作り続ける。
- **採用ゲート（`evidence.collect()`）を緩めない。** TikTok 版も同じゲートを通る。
  `load_tiktok_script` は `load_script` を呼んでおり、`source_url` の検証は共通。
  **ここを迂回する経路を足さない。**
- **`state/*.json` を手で編集しない**（`tiktok_queue.json` / `tiktok_posted.json` を含む）。
- **`work/<id>/tiktok/` を投稿前に消さない。** キューが `video.mp4` を参照する。
- **PKCE の `code_challenge` を base64url に変えない。** TikTok は hex の SHA256。
- 長尺（16:9）は当面作らない。乗る面が無く、関連動画からの回遊も15日で1再生。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする。
- ログを PowerShell で読むときは `Get-Content -Encoding UTF8`。
