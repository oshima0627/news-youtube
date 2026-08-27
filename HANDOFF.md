# HANDOFF

最終更新: 2026-08-27（セッション: Studio 調査 → `--script` 追加 → ビザ手数料の1本を予約）

## いま何をしているのか

**Anthropic の認証がこのPCに無い状態でも1本作れるようにして、実際に1本作って予約した。**
台本の文章は対話セッション（Claude Code）が書き、`--script` でパイプラインに渡した。

## 今回やったこと

### 1. `run_daily.py --script PATH` を足した（新機能）

台本を生成せず、JSONファイルの文章を使う経路。**作り手だけを差し替え、
それより後ろ（引用カードの検証・音声合成・動画合成・アップロード）は
モデルが書いた場合と完全に同じ経路を通る。**

- `scripts/script_writer.py`: `load_script(path, evidence)` と `ScriptMismatch` を追加。
  台本ファイルには Script の全項目に加えて **`source_url` を必須**にし、実行時に
  `evidence.collect()` が選んだ一次資料と一致しなければ受け付けない。
  一致を見ないと、検索語の当たり順が変わっただけで「Aの発言の出典キャプションが
  付いた画面に、Bの発言についての原稿」が乗る。
- `scripts/run_daily.py`: `--script` を追加。`--keyword` か `--only` が無ければ
  `ap.error`（RSSの並び順で題材が決まる経路に人の原稿を渡すと別の題材に付く）。
  `--limit 1` 以外との併用も拒否。`ScriptMismatch` は題材を飛ばさず実行ごと中止。
- テスト: `tests/test_script_writer.py` に6件、`tests/test_run_daily.py` に4件追加。

### 2. その経路で1本作って予約した

```bash
python scripts/run_daily.py --keyword "査証 手数料" \
  --script <台本.json> --days-ahead 3 --limit 1
```

### 3. Studio をAPIで実測した（1つ前のセッション分をここに残す）

## 検証済みの事実（実際に画面に出した出力）

### 今回の1本

- **`pytest` 424 passed**（`--script` 追加後）。
- **アップロードと予約が通った**:
  `✓ 予約しました: https://www.youtube.com/watch?v=8zGOoD1GhUQ → 2026-08-30T18:30:00+09:00`
- **API で引き直して予約を確認した**（アップロード直後の欠け対策）:
  `publishAt: 2026-08-30T09:30:00Z`（＝8/30 18:30 JST）/ `privacyStatus: private` /
  `duration: PT59S`。`tags` は `None` で返るが、これは既知の API の癖。
- **尺**: `試行1: speedScale=0.970 → 実尺58.54秒`、`voice.wav 58.54秒 → video.mp4 58.54秒（差 +0.00秒）`。
- **一次資料**: 第221回国会 参議院法務委員会 2026-05-28 横山信一
  https://kokkai.ndl.go.jp/txt/122115206X01120260528/103
  引用「この査証手数料は一九七八年以来値上げされていない」。
  **見出しと引用の噛み合いは人が見て確認した**（引用そのものに 3,000円→15,000円・
  1978年以来・五倍 が入っている）。
- **画像**: Commons の横山信一の写真（ja.wikipedia 経由）。発言者と一致。
- **テロップのはみ出しを潰した。** 初回ビルドで
  `1978年以来値上げされていない」。` が **1140px**（画面1080px）になって
  最後の「。」が切れていた（フレーム画像で確認）。原稿を書き換えて 0 にした
  （`C:\Users\oshim\AppData\Local\Temp\claude\check_telop.py` で全行の幅を測定）。

### Studio の実測

- 認証は生きている。`viewCount 1,325,814 / subscriberCount 2,880 / videoCount 198`、
  `isChannelMonetizationEnabled: false`。
- **長尺 `UqjB--sNTKk` は7日で 2 再生。** ショート38本から関連動画でリンクしたが
  回遊は起きていない。同期間のショートは1本あたり約1,000〜1,400再生。
- **`R_dirwcTjqs`（8/21公開）だけ 26 再生。** 前後が1,200前後。理由は不明。
- **`8ebRhoO41tM` は private・予約=本日18:30 JST なのに 1,461再生・13高評価。**
  `snippet.publishedAt` が `veU-6dJhtR0` と19秒差で同じ枠（8/17 07:30）に並ぶ。
  → **推測（未確認）**: 8/17 07:30 に2本重なって公開され、片方を private に戻して
  8/27 18:30 へ付け替えた。**本人の判断で「そのままにする」ことにした**（再公開させる）。
- **`zC8OJmUT9Us` は private・予約なし・1,147再生。** 一度公開されて private に戻っている。
- **ローカルの `watch_channel.py` は HTTP 404 で失敗する。** 別チャンネル
  （Google Developers）の feed も同じく404、かつ **GitHub Actions の watchdog は
  8/26 まで success**（`gh run list`）。→ チャンネルの異常ではなく、
  **この回線から YouTube の RSS が引けないだけ**。watchdog は正常。

## 未検証のもの

- **`ANTHROPIC_API_KEY` は依然として無い。** `--script` を使わない通常の
  `run_daily.py` / `run_long.py` は今も動かない（`ScriptWriterUnavailable` で中止）。
- **`--script` 経路の本番実走は今回の1回だけ。** 8/30 18:30 に実際に公開されるかは未確認。
- 予約8本（今回の1本を含む）の見出しと引用の噛み合いは、今回の1本以外は未確認。
- `8ebRhoO41tM` の重複公開・再スケジュールの経緯は推測。ログは残っていない。
- `R_dirwcTjqs` が 26 再生に留まる理由は不明。
- **テロップの禁則処理は直していない。** `draw.wrap()` は行頭禁則で行が幅を
  超えることを許しており、`」` `。` が続くと画面外に出る。既存10本448行のうち
  1行（公開済みの `work/b3f6f9e5cd12`「四百十三万人となっております」。= 1120px）が
  同じ状態。**別タスクとして切り出してある。**

## 次にやること

1. **8/30 18:30 JST に `8zGOoD1GhUQ` が公開されたか見る。**

   ```bash
   python scripts/upload_youtube.py --auth-only
   ```

2. **次の1本も `--script` で作る**（認証が無いままなら）。空き枠は 8/30 07:30 の次、
   つまり 8/31 07:30 JST 以降。題材は `--keyword` で国会会議録を直接掘るほうが当たる。

   ```bash
   python scripts/yield_report.py --refresh    # RSS候補を見る（既出の続報が多い）
   python scripts/run_daily.py --keyword "<2語以上>" --script <台本.json> --days-ahead 4 --limit 1
   ```

   台本JSONの書式は `scripts/script_writer.load_script` の docstring と
   `tests/test_script_writer.py` の `HAND_WRITTEN` を見る。**`source_url` 必須。**

3. **`ANTHROPIC_API_KEY` を用意すれば通常経路に戻せる。** `--script` は残しておいてよい。

4. **長尺の方針を決める。** 導線（関連動画38本）を張っても 2 再生だった。
   本数を増やす前に、題材かサムネイルか、どちらを測るかを決める。

5. `zC8OJmUT9Us` を公開に戻すか消すか決める（1,147再生あるが現在 private）。

## 触ってはいけないところ

- 採用ゲート（`evidence.collect()`）を緩めない。**`--script` は台本の作り手を
  変えるだけで、採用ゲートも引用カードの検証も従来どおり通る。ここを迂回する
  経路を足さない。**
- 台本ファイルの `source_url` 必須をやめない。突き合わせが無いと、別の発言の
  出典キャプションが付いた画面に無関係な原稿が乗り、しかも画面上は
  一次資料付きに見える。
- `state/*.json` を手で編集しない。
- **ローカルの `watch_channel.py` の 404 を「チャンネルが止まった」と読まない。**
  判定は GitHub Actions の watchdog を見る。
- 「関連動画」は API から読めない。設定したらその場で画面で確かめる。
  新しく作ったショート（`8zGOoD1GhUQ` を含む）には**まだ設定していない**。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする。
