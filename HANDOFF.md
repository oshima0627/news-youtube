# HANDOFF

最終更新: 2026-08-31（セッション: TikTok 投稿の実装 → アプリ登録 → Sandbox 構築。
本人の作業待ち: Sandbox の client_key / client_secret を置くこと）

## いま何をしているのか

**TikTok にも投稿できるようにしている。** ショートと同じ一次資料・同じ引用から、
本文だけを長く書いた **70〜80秒版**を `work/<id>/tiktok/` に作り、YouTube の枠と
同じ時刻に Direct Post API で投稿する。

**コードは完成していて全経路を通した。Sandbox も実 API を叩ける状態まで設定した。**
Production 側の未入力は**デモ動画だけ**。ただしポータルは全項目が埋まるまで下書き
保存できないので、**Production の入力はまだブラウザのタブ上にしかない**
（下記「いま詰まっているところ」）。

**次の一手は本人の作業**: Sandbox の `client_key` / `client_secret` を
`tiktok_client.json` に置くこと。置けば `--auth-only` で**実 API に初めて到達する**。

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

### 3. TikTok 開発者アプリを作り、デモ動画以外を全部入れた

本人が開発者アカウントを作成してログインしたあと、ブラウザ操作で進めた。
**入力した値は全部 [`docs/tiktok-app-registration.md`](docs/tiktok-app-registration.md) に控えてある。**

### 4. Sandbox（`local-desktop`）を作って設定した

ID `7679915999907088404`。**未承認アプリは Sandbox で実演したデモ動画でないと
審査に出せない**うえ、実 API を審査前に叩けるので HTTP 部分の検証にも使う。
設定内容は [`docs/tiktok-app-registration.md`](docs/tiktok-app-registration.md)。

### 5. 手で置く認証情報ファイルを BOM 付きでも読めるようにした

`tiktok_client.json` は人がエディタで作る。Windows のエディタは UTF-8 に BOM を
付けて保存することがあり、`json.loads` はそれで落ちる。出るのは「JSONとして
読めません」だけで原因に辿り着けないので、`utf-8-sig` で読むようにした。

### 6. 審査に要る3ページを Cloudflare Workers で公開した

`site/`（`wrangler.jsonc` + `src/index.js`）。`cd site && npx wrangler deploy`。
利用規約・プライバシーポリシー・サービス説明と、URL 所有確認の署名ファイルを配信する。
**ページの記述は実装と一致させてある**（保存するトークンの種類と置き場所、
要求するスコープ2つ、一次資料の扱い）。実装を変えたら `site/src/index.js` も直す。

## 検証済みの事実（実際に画面に出した出力）

- **`pytest` 545 passed**（前回 435 → 今回 +110）。警告なし。
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
  Redirect URI(Desktop)=`http://localhost:8723/callback` / App review の説明文(922字) /
  App icon / 3つのURL。**エラーは 6 → 1（デモ動画のみ）まで減った。**
- **Save が拒否されることを確認した**:

  ```
  Please correct all errors before you save changes, or submit changes for review.
  ```

- **URL の所有確認が通った**: `Your property has been verified` /
  URL prefix `https://kokkai-news-maruwakari.oshima6-27.workers.dev/` / Verified。
- **3ページが公開されていることを確認した**（`/` `/terms` `/privacy` が 200、
  未定義パスは 404、署名ファイルが 68バイトで一致、連絡先 `info@nexeed-lab.com` を掲載）。
- **誤った名前の Worker を消した**: `Successfully deleted kokkai-news-marukawari`、
  旧URLは HTTP 404。TikTok 側の旧 URL prefix も `Delete success` で削除済み。
  （`marukawari` は誤り。まるわかり＝`maruwakari`）
- **Sandbox を作って設定した。再読み込み後も残っていることを確認した**:
  Target Users=`naotaka_oshima`(11:50 追加) / Products=Login Kit + Content Posting API /
  Direct Post=ON / Scopes=`user.info.basic`,`video.publish`,`video.upload` /
  Redirect URI(Desktop)=`http://localhost:8723/callback` /
  Category=News / Description / 3つのURL / App icon。
- **Client secret のページからの読み出しは安全機構に止められた**（妥当な動作。
  秘密鍵を会話の記録に残さずに済む）。**本人が手で置く方針に切り替えた。**

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

| 項目 | 状況 |
|---|---|
| Sandbox の認証情報 | **本人の作業待ち。** `client_key` / `client_secret` を `tiktok_client.json` に置く |
| デモ動画（Production） | **未着手。** Sandbox での端から端までの画面録画が必要 |

**Production はデモ動画が埋まるまで Save も Submit もできない。** つまり
いまタブ（`.../pending`）を閉じると App icon・3つのURL・説明文の入力が消える
（URL の所有確認だけはポータル側に保存されているので残る）。再入力は
`docs/tiktok-app-registration.md` を見れば機械的にできる。

**Sandbox 側は Apply changes 済みなので保存されている。**

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

1. **本人が Sandbox の認証情報を置く**（依頼済み）:
   `C:\Users\oshim\Documents\projects\news-youtube\tiktok_client.json` に
   `{"client_key": "...", "client_secret": "..."}`。
   取得元は https://developers.tiktok.com/app/7679774568128202772/sandbox/7679915999907088404
   の上部 Credentials（**タブが Sandbox であることを確認する。Production の鍵では
   Sandbox の投稿は通らない**）。置かれたらワークツリーへコピーして使う。

2. **`python scripts/upload_tiktok.py --auth-only` を実行する。**
   同意画面は**私の操作できないウィンドウで開くので本人にクリックしてもらう**
   （Sandbox の Target User 追加のときもそうだった）。通れば OAuth と
   `creator_info` に**初めて実到達**する。Sandbox なので
   `privacy_level_options` は `SELF_ONLY` だけになるはず。

3. **`--allow-self-only` で1本投稿してみる。** 通れば `publish` /
   `status/fetch` まで実検証できる。デモ動画で見せる内容もこれで確定する。

4. **デモ動画を録る。** Developer Portal の **Sandbox** タブを使い、
   `upload_tiktok.py --auth-only` → 動画の投稿 → TikTok 上での結果、までを
   画面録画する（mp4/mov、50MB以下）。**未承認アプリは Sandbox での実演が必須。**

5. **録れたらアップロードして Save → Submit for review。**
   **申請ボタンは本人の確認を取ってから押すこと。**

6. **審査が下りたら Production の鍵に差し替えて1本投稿する**:

   ```bash
   python scripts/upload_tiktok.py --auth-only     # 審査状態も表示される
   python scripts/run_daily.py --keyword "<2語以上>" \
     --script <短尺台本.json> --tiktok-script <TikTok台本.json> \
     --days-ahead <N> --limit 1
   python scripts/post_tiktok_due.py --dry-run     # キューを確認
   ```

7. **定時タスクを登録する**（枠の時刻に実際に投げる）:

   ```
   schtasks /create /tn "tiktok-0725" /sc daily /st 07:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   schtasks /create /tn "tiktok-1825" /sc daily /st 18:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   ```

8. **9/2 以降の YouTube の枠を埋める**（空きは 9/2 07:30 から）。実測済みで未使用の
   検索語: `医師偏在指標 新潟`、`外国人 土地`。

9. **8/31 以降に `myjKRuLTmXw`（教員不足）の再生数を他の回と比べる**
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
- **署名ファイルの中身を画面から書き写さない。** ダウンロードした実物をコピーする
  （`l` と `I` が画面で見分けられない）。URL prefix を変えると別のコードが発行される。
- **`site/src/index.js` の記述と実装を食い違わせない。** 審査はここを突き合わせる。
- **Sandbox と Production の client_key / client_secret を混ぜない。** 別物で、
  取り違えると投稿が通らない。`tiktok_client.json` をどちらの鍵にしているか意識する。
- **client_secret を会話やコミットに残さない。** 本人が手で置く。
- 長尺（16:9）は当面作らない。乗る面が無く、関連動画からの回遊も15日で1再生。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする。
- ログを PowerShell で読むときは `Get-Content -Encoding UTF8`。
