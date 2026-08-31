# HANDOFF

最終更新: 2026-08-31（セッション: TikTok 投稿の実装 → 開発者アプリの登録を途中まで進めた）

## いま何をしているのか

**TikTok にも投稿できるようにしている。** ショートと同じ一次資料・同じ引用から、
本文だけを長く書いた **70〜80秒版**を `work/<id>/tiktok/` に作り、YouTube の枠と
同じ時刻に Direct Post API で投稿する。

**コードは完成していて全経路を通した。いま止まっているのは TikTok 側のアプリ登録。**
開発者アプリは作成済みだが、**必須項目が5つ埋まらず、下書き保存すらできない状態**
（下記「いま詰まっているところ」）。

YouTube の運用は変わっていない: **枠は 2026-09-01 18:30 JST まで埋まっている
（予約11本）。次の空きは 9/2 07:30。** `ANTHROPIC_API_KEY` は無いので、台本は
対話セッションが書いて `--script` で渡す。

## 今回やったこと

### 1. TikTok 投稿の一式を実装した（TDD、新規109テスト）

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

### 2. 動画を1本作って、投稿経路を最後まで通した（`--dry-run`）

```bash
python scripts/run_daily.py --keyword "医師偏在指標 新潟" \
  --script <短尺台本.json> --tiktok-script <TikTok台本.json> \
  --dry-run --days-ahead 3 --limit 1
```

### 3. TikTok 開発者アプリを作り、設定を途中まで入れた

本人が開発者アカウントを作成してログインしたあと、ブラウザ操作で進めた。
**入力した値は全部 [`docs/tiktok-app-registration.md`](docs/tiktok-app-registration.md) に控えてある。**

## 検証済みの事実（実際に画面に出した出力）

- **`pytest` 544 passed**（前回 435 → 今回 +109）。警告なし。
- **同じ題材から2本ビルドできた**（`work/1d04e9d8cd04/`）:

  ```
  試行1: speedScale=0.945 → 実尺58.67秒（許容範囲内）
    尺: voice.wav 58.67秒 → video.mp4 58.67秒（差 +0.00秒）  テロップ22枚
  試行1: speedScale=0.949 → 実尺74.14秒（許容範囲内）
    尺: voice.wav 74.14秒 → video.mp4 74.17秒（差 +0.02秒）  テロップ28枚
  ```

  **TikTok版は 74.17秒。** ffprobe で実測し、`tiktok.assert_over_a_minute` を通過。
- **投稿経路を実物で最後まで通した**（送信先の API だけ差し替え。それ以外＝
  尺の測定・3つの関門・キャプション生成・完了確認・キューの記録は本番と同じコード）:

  ```
  publish_id: publish-sim-1 / privacy_level: PUBLIC_TO_EVERYONE
  duration: 74.166667 / status: PUBLISH_COMPLETE
  source_info: {"video_size": 3036922, "chunk_size": 3036922, "total_chunk_count": 1}
  キュー: 枠前(07:00)→[] / 枠後(07:30)→[work/1d04e9d8cd04/tiktok] / 投稿後→[]
  ```

- **キャプションは 153 runes**（上限2200）。画面を目視で確認（`stage.png` /
  `frames/002.png`）。被写体は小林一大本人で発言者と一致。引用カードは
  「医師偏在指標で全国第44位」で逐語引用の部分文字列。
- **テロップのはみ出しは実質なし。** 両版とも最大右端 1054px、画面幅 1080px の内側。
- **開発者アプリを作成した。** App ID `7679774568128202772`、Ownership **Individual**、
  App type **Other**（どちらも作成後は変更不可）。
- **入力できた項目**: App name / Category=News / Description(112字) /
  Platforms=Desktop / Products=Login Kit + Content Posting API /
  **Direct Post=ON** / Scopes=`user.info.basic`,`video.publish`,`video.upload` /
  Redirect URI(Desktop)=`http://localhost:8723/callback` / App review の説明文(922字)。
- **Save が拒否されることを確認した**:

  ```
  Please correct all errors before you save changes, or submit changes for review.
  This form has 5 errors.
  ```

- **`wrangler --version` = 4.127.1、`wrangler whoami` は認証済み**（アカウントの
  権限一覧が返った）。
- **TikTok API の仕様を実際のドキュメントで確認した**:
  - 未審査クライアントの投稿は全て SELF_ONLY に強制される
  - Direct Post に `schedule_time` 相当のフィールドは**無い**
  - キャプション上限 2200 UTF-16 runes、`creator_info/query` を先に呼ぶ必要あり
  - PKCE の `code_challenge` は **hex エンコードの SHA256**（base64url ではない）
  - **Desktop アプリとして登録したときだけ** redirect URI に localhost と http が使える
  - アクセストークン24時間 / リフレッシュトークン365日
  - Creator Rewards: 60秒以上・フォロワー1万人・直近30日10万再生・個人アカウント

## いま詰まっているところ

**開発者ポータルのフォームは、必須項目が全部埋まるまで下書き保存できない。**
いま入力した内容は**開いているブラウザのタブ上にしかない**（タブは開いたまま
にしてある）。閉じたら `docs/tiktok-app-registration.md` を見て再入力する。

残り5項目:

| 項目 | 状況 |
|---|---|
| App icon (1024x1024) | **3案を作って本人の選択待ち**（scratchpad の `icon_a/b/c.png`。scratchpad は消えるので、選ばれた案は作り直す。生成コードは下記） |
| Terms of Service URL | **未着手。** Cloudflare Workers で公開すると決まった |
| Privacy Policy URL | 同上 |
| Web/Desktop URL | 同上（サービス説明ページ） |
| デモ動画 | **未着手。** Sandbox 環境での端から端までの画面録画が必要 |

## 未検証のもの

- **TikTok に1本も投稿していない。** HTTP を実際に投げる部分
  （`tiktok_api.TikTokApi` の `creator_info` / `publish` / `_fetch_status` と
  `authorize()` の OAuth 往復）は**一度も本物のサーバに当たっていない**。
- **Content Posting API が個人アカウントで使えるかは未確認。** Business
  アカウント必須だと Creator Rewards（個人アカウント必須）と両立しない。
- **`work/1d04e9d8cd04/tiktok/meta.json` の `expected_tiktok_open_id` は空。**
  認証前に作ったため、このバリアントはこのままでは投稿できない。認証後に作り直す。
- 今回の題材（医師偏在）は YouTube にも投稿していない（`--dry-run`）。
- 定時タスク（schtasks）はまだ登録していない。

## 次にやること

1. **アイコンを決める**（本人の返事待ち。A=見出しと同じ縦棒＋「ニュース」／
   B=鉤括弧に「国会」／C=テロップ帯の三層）。生成し直すコードは
   `docs/tiktok-app-registration.md` には無いので、必要なら作り直す。
   紺 `(16,24,43)` ／ オレンジ `(255,150,26)`、`scripts.draw.pick_font` を使う。

2. **Cloudflare Workers で3ページを公開する。** 利用規約・プライバシーポリシー・
   サービス説明。`wrangler` は認証済みなので、コードを書いて `wrangler deploy`。
   URL が出たらフォームの3項目に入れる。

3. **デモ動画を録る。** Developer Portal の **Sandbox** タブを使い、
   `upload_tiktok.py --auth-only` → 動画の投稿 → TikTok 上での結果、までを
   画面録画する（mp4/mov、50MB以下）。**未承認アプリは Sandbox での実演が必須。**

4. **5項目が埋まったら Save → Submit for review。**
   **申請ボタンは本人の確認を取ってから押すこと。**

5. **審査が下りたら認証して1本投稿する**:

   ```bash
   python scripts/upload_tiktok.py --auth-only     # 審査状態も表示される
   python scripts/run_daily.py --keyword "<2語以上>" \
     --script <短尺台本.json> --tiktok-script <TikTok台本.json> \
     --days-ahead <N> --limit 1
   python scripts/post_tiktok_due.py --dry-run     # キューを確認
   ```

6. **定時タスクを登録する**（枠の時刻に実際に投げる）:

   ```
   schtasks /create /tn "tiktok-0725" /sc daily /st 07:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   schtasks /create /tn "tiktok-1825" /sc daily /st 18:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   ```

7. **9/2 以降の YouTube の枠を埋める**（空きは 9/2 07:30 から）。実測済みで未使用の
   検索語: `医師偏在指標 新潟`、`外国人 土地`。

8. **8/31 以降に `myjKRuLTmXw`（教員不足）の再生数を他の回と比べる**
   （自殺者数に触れているため配信制限の可能性。他の回は約1,200）。

## 触ってはいけないところ

- **`tiktok.TIKTOK_MIN_SECONDS`（61.0秒）を下げない。** 60秒を割った動画は
  Creator Rewards の対象外で、投稿は通るので成功ログだけが積み上がる。
- **未審査ガードを外さない。** `--allow-self-only` は経路確認専用。
- **採用ゲート（`evidence.collect()`）を緩めない。** TikTok 版も同じゲートを通る。
- **`state/*.json` を手で編集しない**（`tiktok_queue.json` / `tiktok_posted.json` を含む）。
- **`work/<id>/tiktok/` を投稿前に消さない。** キューが `video.mp4` を参照する。
- **PKCE の `code_challenge` を base64url に変えない。** TikTok は hex の SHA256。
- **`tiktok_api.DEFAULT_REDIRECT_URI` を変えたら、TikTok アプリ側の登録も同時に
  直す。** 文字列が完全一致でないと同意画面で止まる。
- **開発者ポータルで Submit for review を押す前に本人の確認を取る。**
- 長尺（16:9）は当面作らない。乗る面が無く、関連動画からの回遊も15日で1再生。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする。
- ログを PowerShell で読むときは `Get-Content -Encoding UTF8`。
