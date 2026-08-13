# 毎日の手順

**このファイルのコマンドは、すべてリポジトリ直下で実行する。**
`projects` のままだと `can't open file ... scripts\upload_youtube.py` になる。

```powershell
cd C:\Users\oshim\Documents\projects\news-youtube
```

## 初回だけ（オーナーが行う）

1. **YouTube認証**

   ```bash
   python scripts/upload_youtube.py --auth-only
   ```

   ブラウザが開くので、Googleアカウントの同意画面で
   **「日本の最新ニュースまるわかり」** を選ぶこと。
   別チャンネル（個人アカウント等）を選ぶと、`token.json` がそのチャンネルに
   紐づいてしまい、以後のアップロードが `assert_expected_channel` の
   チャンネル取り違えガードに引っかかって毎回失敗する。
   成功すると `✓ 認証しました: 日本の最新ニュースまるわかり（UCYHTfHJOoETzvpx-VZlUTng）`
   と表示され、`token.json` が作られる（コミットしないこと。`.gitignore` 済み）。

2. **環境変数を設定する**

   | 変数 | 用途 |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | 台本生成（`script_writer.write`）に必須 |
   | `ESTAT_APP_ID` | e-Stat 系統を復活させたときに必須（現状は未使用） |

   `ANTHROPIC_API_KEY` が無い（または無効）だと `run_daily.py` は
   **候補を1件も無駄にせず最初の1件で即座に中止する**。「見送り」を
   全候補ぶん繰り返してから「0本でした」とだけ表示される最悪の失敗を避けるため。

3. **VOICEVOX エンジンを用意する**

   `http://127.0.0.1:50021/speakers` が応答する状態にしておく。
   `narrate.ensure_engine()` が未起動なら既知の候補パスから自動起動を試みるが、
   見つからなければ手動起動を促すメッセージを出して止まる。

## 1本作るとき

```bash
python scripts/run_daily.py
```

翌日分を先に作るときは `--days-ahead 1`（当日の枠が過ぎていても作れる）:

```bash
python scripts/run_daily.py --days-ahead 1
```

**1枠ぶんだけ作り直すときは `--limit` を付ける。** 予約済みの動画を
`unpublish.py` で戻して差し替える場合など、その日の残り枠が2つあっても
1本しか作りたくないことがある。`--days-ahead` だけだと残り全部を作って
しまい、**すでに予約済みの枠に2本目が重なる**（`upload_youtube.py` に
重複防止が無いので、同じ時刻に2本並ぶ）。埋まるのは早い方の枠から。

```bash
python scripts/run_daily.py --days-ahead 1 --limit 1
```

**手で起動する運用。** その時点の残り枠の数だけ作り、07:30 / 18:30 の予約公開に
載せて終わる。PC が日中落ちていても YouTube 側が定刻に公開する。
毎朝の自動起動にしたい場合は末尾「タスクスケジューラへの登録（任意）」を参照。

画像の事前準備は要らない。**発言者の顔写真を自動で取ってくる**（下記「画像」）。

```
run_daily.py
  ├─ collect_news.py          RSS巡回 → 候補20件
  │                           天気・スポーツ等は候補にしない
  └─ 候補を上から順に
       ├─ 当日すでに使った出来事・発言なら見送り
       ├─ evidence.collect()  ★採用ゲート（根拠が無ければ見送り）
       ├─ commons.resolve()   発言者の顔写真を自動取得（下記「画像」参照）
       ├─ script_writer.write()   一次資料だけを渡して台本生成
       ├─ narrate.synthesize()    VOICEVOXで音声合成
       ├─ build_short.build()     図解カード + テロップ + 音声 → 1080x1920
       └─ upload_youtube.py       private → --schedule で 07:30 / 18:30 予約
```

失敗したときの扱いは「環境不備」か「題材固有」かで分かれる。

- **環境不備 → 日次実行そのものをその場で中止**（原因がログにそのまま出る、
  終了コードは1）。次に該当する:
  - `collect_news.py` が終了コード**1**を返したとき（全RSSフィードの取得失敗）。
    ただし終了コード**2**（`EXIT_NO_TOPIC`＝フィードは取れたが、国会で
    議論されえない題材と既出を除いたら何も残らなかった）は環境不備では
    ないので中止しない。0本の日として静かに終える
  - `evidence.collect()` の `EvidenceSourcesUnavailable` が**連続3候補**で
    起きたとき、または全候補で起きて一度も取得に成功しなかったとき。
    系統が国会会議録の1つしか無いため1回のタイムアウトでもこの例外になるので、
    1件では中止しない（`search_speeches` 側でも指数バックオフで再試行する）
  - `script_writer.write()` が `ScriptWriterUnavailable` を送出したとき
    （`ANTHROPIC_API_KEY` 未設定・無効など）
  - `narrate.synthesize()` が VOICEVOX に接続できず例外を送出したとき
  - `upload_youtube.py` が終了コード**3**（チャンネル取り違え）を返したとき。
    `token.json` が別チャンネルに紐づいている状態で、どの題材でも必ず失敗する

  これらはどの題材で起きても同じ理由で確実に失敗するため、他の候補を
  試しても無駄だと分かっている。飛ばして次に進む設計のままだと、全候補ぶん
  同じ失敗を繰り返した末に「本日 0/2 本」とだけ表示され、ログを見るまで
  環境不備だと気づけない。それを避けるため即座に中止する。

- **題材固有 → その題材だけ飛ばして残りの枠は処理を続ける。** 次に該当する:
  - `script_writer.write()` が `ScriptGenerationRejected` を送出したとき
    （Anthropic の安全フィルタによる refusal、構造化出力の失敗など。
    政治ニュースを扱う以上、特定の題材の内容だけが理由で起こりうる）
  - 画像を取得できなかったとき（発言者の記事画像も国会議事堂も取れない、
    Wikimedia 側の障害など）
  - `build_short.build()` の失敗（ffmpeg関連など）
  - `upload_youtube.py` の一時的なエラー（取り違えの終了コード3は除く）。
    ただし**1回目の private アップロードが成功した後**に `--schedule` が
    落ちた場合は、動画が既に YouTube 上にあるので既出（`state/seen.json`）に
    入れる。入れないと翌日また同じ題材を作って同じ動画をもう1本上げてしまう
    （`upload_youtube.py` に重複防止が無い）。ログに
    「アップロード自体は成功しています」と出たら、YouTube Studio で private の
    まま残っていないか確認して手動で公開する

- **`--dry-run` 実行時** — アップロードを一切行わないため、`state/seen.json`
  も更新しない（更新してしまうと、動作確認のつもりで手動 `--dry-run` した
  題材が本番実行では二度と拾われず、その日は無投稿のまま終わってしまう）。

- **予約枠を過ぎてしまったとき** — 収集〜台本〜音声合成〜動画合成〜
  アップロードには数分かかりうる。18:30直前に起動したときなど、
  アップロード直前に確認した時点で対象の枠がすでに過去になっていることが
  ある。その場合は `--schedule` を呼ばず private のまま残し、
  「要手動公開」の警告とともに手動で公開するコマンド
  （`upload_youtube.py <workdir> --publish`）を表示する。動画自体は
  アップロード済みなので既出（`state/seen.json`）には入れる
  （入れないと翌日また同じ題材が処理され、`upload_youtube.py` には
  重複防止の仕組みが無いため同じ内容の動画がもう1本アップロードされて
  しまう。private のまま取り残される方が実害が小さい）。

## 手で見るもの

- **朝** — 実行ログで「本日 N/2 本」を確認する。
  - 「見送り（同じ出来事を最近すでに使用）」「見送り（同じ発言を最近すでに使用）」
    は正常。同じ出来事の見出しが各社から並んだときに似た動画が続くのを
    防いでいる。直近14日ぶんを `state/used.json` に記録している。
  - `state/empty_streak.json` の `days` が3以上になると
    「N日続けて0本です。RSSの配点か採用ゲートを見直してください」と警告が出る。
    収益化要件（90日で3本以上）に対する早期警戒。
  - 終了コードが1のときは環境不備の疑いがある（メッセージに原因が出る）。
    ログを確認して `ANTHROPIC_API_KEY` / VOICEVOX の状態を直す。

- **画像** — 事前準備は要らない。`run_daily.py` が発言者名から
  **ja.wikipedia のその人物の記事画像**を取り、Commons でライセンス
  （CC BY / CC BY-SA / CC0 / PD のみ）と大きさを確かめて使う。
  人物名の全文検索は使っていない（別人や集合写真が混ざり、誰が写っているかを
  機械的に確かめられないため）。記事と人物は1対1なので写っている人物が確定する。

  発言者の画像が無いとき（政府参考人など。実測で11人中3人）は
  **国会議事堂の写真**に落ちる。国会での発言を扱う番組なので、題材が
  何であっても文脈から外れない。両方だめなときだけ、その題材を見送る。

  自動で選ばれた画像が題材に合わないときは、手で差し替えられる:

  ```bash
  python scripts/fetch_photo.py work/<id> --speaker 片山さつき   # 別の人物で探す
  python scripts/fetch_photo.py work/<id> <画像URL>              # URLを直接指定
  ```

  `run_daily.py` は `photo.jpg` と `license.json` が既にあれば自動取得を
  行わないので、置いた画像は次の実行でも尊重される。
  URLを直接指定する場合の取得元は首相官邸・各府省（`*.go.jp`）と
  Wikimedia Commons（`upload.wikimedia.org`）のみで、ホワイトリスト外は
  `ValueError` で弾かれる。

## 事故ったとき

```bash
python scripts/unpublish.py <video_id>   # 1本だけ戻す
python scripts/unpublish.py --all-today  # 当日分を全部戻す
```

いずれも `privacyStatus` を `private` に戻すだけで、動画自体は消さない。

`--all-today` は1本が失敗しても残りを必ず試し、最後に「N件中M件成功」を出す。
失敗があれば終了コード1で、戻せなかった動画のURLを stderr に列挙する
（**そのURLは公開されたままの可能性がある**ので、YouTube Studio で直接
非公開にすること）。

## 前提の確認（チェックリスト）

- [ ] VOICEVOX が起動していること（`http://127.0.0.1:50021/speakers` が応答する）
- [ ] `ANTHROPIC_API_KEY` が環境変数にあること
- [ ] `token.json` が `UCYHTfHJOoETzvpx-VZlUTng`（日本の最新ニュースまるわかり）
      に紐づいていること（`python scripts/upload_youtube.py --auth-only` で確認できる）
- [ ] （画像の事前準備は不要。発言者から自動で取る）

## タスクスケジューラへの登録（任意）

手で起動する運用なら不要。毎朝自動で走らせたい場合だけ、
**管理者権限の PowerShell** で実行する（オーナー自身が登録すること）:

```powershell
schtasks /create /tn "news-youtube" /tr "python C:\Users\oshim\Documents\projects\news-youtube\scripts\run_daily.py" /sc daily /st 06:00 /f
```

成功すると次のように表示される:

```
成功: スケジュール タスク "news-youtube" は正しく作成されました。
```

登録を確認する:

```powershell
schtasks /query /tn "news-youtube" /v /fo list
```

削除する場合:

```powershell
schtasks /delete /tn "news-youtube" /f
```
