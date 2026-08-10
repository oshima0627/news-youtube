# 毎日の手順

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

## 自動で走るもの

タスクスケジューラが毎朝 06:00 に `run_daily.py` を起動する。
当日の残り枠の数だけ作り、07:30 / 18:30 の予約公開に載せて終わる。
PC が日中落ちていても YouTube 側が定刻に公開する。

```
06:00  run_daily.py
  ├─ collect_news.py          RSS巡回 → 候補20件
  └─ 候補を上から順に
       ├─ evidence.collect()  ★採用ゲート（根拠が無ければ見送り）
       ├─ 画像が無ければ見送り（下記「画像」参照）
       ├─ script_writer.write()   一次資料だけを渡して台本生成
       ├─ narrate.synthesize()    VOICEVOXで音声合成
       ├─ build_short.build()     図解カード + 音声 → 1080x1920
       └─ upload_youtube.py       private → --schedule で 07:30 / 18:30 予約
```

失敗したときの扱いは「環境不備」か「題材固有」かで分かれる。

- **環境不備 → 日次実行そのものをその場で中止**（原因がログにそのまま出る、
  終了コードは1）。次に該当する:
  - `evidence.collect()` が `EvidenceSourcesUnavailable` を送出したとき
    （国会会議録APIなど一次資料の取得元が1系統も応答しなかった場合。
    「根拠が無かった」という正常系の空リストとは区別されている）
  - `script_writer.write()` が `ScriptWriterUnavailable` を送出したとき
    （`ANTHROPIC_API_KEY` 未設定・無効など）
  - `narrate.synthesize()` が VOICEVOX に接続できず例外を送出したとき

  これらはどの題材で起きても同じ理由で確実に失敗するため、他の候補を
  試しても無駄だと分かっている。飛ばして次に進む設計のままだと、全候補ぶん
  同じ失敗を繰り返した末に「本日 0/2 本」とだけ表示され、ログを見るまで
  環境不備だと気づけない。それを避けるため即座に中止する。

- **題材固有 → その題材だけ飛ばして残りの枠は処理を続ける。** 次に該当する:
  - `script_writer.write()` が `ScriptGenerationRejected` を送出したとき
    （Anthropic の安全フィルタによる refusal、構造化出力の失敗など。
    政治ニュースを扱う以上、特定の題材の内容だけが理由で起こりうる）
  - 画像未準備（下記「画像」参照）
  - `build_short.build()` の失敗（ffmpeg関連など）
  - `upload_youtube.py` の一時的なエラー

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
  - `state/empty_streak.json` の `days` が3以上になると
    「N日続けて0本です。RSSの配点か採用ゲートを見直してください」と警告が出る。
    収益化要件（90日で3本以上）に対する早期警戒。
  - 終了コードが1のときは環境不備の疑いがある（メッセージに原因が出る）。
    ログを確認して `ANTHROPIC_API_KEY` / VOICEVOX の状態を直す。

- **画像** — `run_daily.py` は画像を自動取得しない（人物・場面が題材ごとに
  違うため）。翌朝の候補になりそうな題材が見えたら、あらかじめ

  ```bash
  python scripts/collect_news.py --limit 20   # 候補一覧を work/candidates.json に作る
  python scripts/fetch_photo.py work/<id> <画像URL>
  ```

  で `work/<id>/photo.jpg` と `license.json` を用意しておく。
  取得元は首相官邸・各府省（`*.go.jp`）と Wikimedia Commons
  （`upload.wikimedia.org`）のみに限定されており、ホワイトリスト外のURLは
  `ValueError` で弾かれる（詳細は README の「画像素材」を参照）。
  画像が無いまま `run_daily.py` の実行時刻を迎えた題材は、
  「見送り（画像未準備）」というメッセージとともに**その題材だけ**飛ばされ、
  `work/` に残るので翌日以降にまた候補として拾われる。

## 事故ったとき

```bash
python scripts/unpublish.py <video_id>   # 1本だけ戻す
python scripts/unpublish.py --all-today  # 当日分を全部戻す
```

いずれも `privacyStatus` を `private` に戻すだけで、動画自体は消さない。

## 前提の確認（チェックリスト）

- [ ] VOICEVOX が起動していること（`http://127.0.0.1:50021/speakers` が応答する）
- [ ] `ANTHROPIC_API_KEY` が環境変数にあること
- [ ] `token.json` が `UCYHTfHJOoETzvpx-VZlUTng`（日本の最新ニュースまるわかり）
      に紐づいていること（`python scripts/upload_youtube.py --auth-only` で確認できる）
- [ ] 直近の候補に画像（`work/<id>/photo.jpg` + `license.json`）を用意済みであること

## タスクスケジューラへの登録

**管理者権限の PowerShell** で実行する（このリポジトリの自動化フローでは実行していない。
オーナー自身が管理者権限で登録すること）:

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
