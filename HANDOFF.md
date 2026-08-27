# HANDOFF

最終更新: 2026-08-27（セッション: Studio 調査 → 次の1本の題材決め）

## いま何をしているのか

**Studio（チャンネルの実測）を一通り見た。次の1本の題材まで決めて、
一次資料も引き当てた。ただし台本生成が Anthropic の認証不在で動かず、
動画そのものは作れていない。** コードは変更していない。

## 今回やったこと

### 1. Studio をAPIで実測した（コードは触っていない）

`token.json` は生きている。`channels.list(mine=True)` の出力:

```
日本の最新ニュースまるわかり UCYHTfHJOoETzvpx-VZlUTng
stats:  {"viewCount":"1325814","subscriberCount":"2880","videoCount":"198"}
status: {"privacyStatus":"public","isLinked":true,"longUploadsStatus":"allowed",
         "isChannelMonetizationEnabled":false}
```

`playlistItems`＋`videos.list` で直近40本の privacyStatus / publishAt / viewCount を並べた。

### 2. 最新ニュースを調べ、題材を1件に絞った

- RSS 候補（`yield_report.py --refresh`）は 20件中 採用可6件だが、
  上位は消費税減税・熊本地震・GPIF で**すでに動画にした出来事の続報**が大半。
- 代わりに Web 検索で拾った「**訪日ビザ手数料が1978年以来48年ぶりに値上げ
  （一次有効査証 3,000円 → 15,000円）、2026年7月1日申請分から適用**」を
  `--keyword` 経路で国会会議録に当て、**当たった**。

## 検証済みの事実（実際に画面に出した出力）

- **認証は生きている。** 上記 `channels.list` が返った（8/26 に一度死んだ件は再発なし）。
- **長尺 `UqjB--sNTKk` は7日で 2 再生。** ショート38本から関連動画で
  リンクしたが、**回遊は起きていない**（前回セッションの次アクションの答え）。
  同期間のショートは1本あたり約1,000〜1,400再生。
- **`R_dirwcTjqs`（8/21 18:30公開）だけ 26 再生。** 前後のショートが1,200前後の中で
  桁が2つ違う。privacyStatus は public。
- **`8ebRhoO41tM` は private・publishAt=2026-08-27T09:30Z（＝本日18:30 JST）なのに
  viewCount 1461・likeCount 13。** 予約中の動画に再生数は付かない。
  `snippet.publishedAt` は 2026-08-16T22:30:04Z で、`veU-6dJhtR0` の
  2026-08-16T22:30:23Z と**同じ枠（8/17 07:30 JST）に19秒差で並んでいる**。
  → **推測（未確認）**: 8/17 07:30 の枠に2本重なって公開され、あとから
  片方を private に戻して 8/27 18:30 へ付け替えた。誰がいつ操作したかは不明。
  **本日18:30に、すでに1,461再生ある動画がもう一度公開される。**
- **`zC8OJmUT9Us` は private・publishAt 無し・viewCount 1147。** 一度公開されて
  private に戻された状態。`published.json` にも `publish_at` が無い。
- **`watch_channel.py` はこの PC からだと HTTP 404 で失敗する。**
  ただし別チャンネル（Google Developers）の feed も同じく404、かつ
  **GitHub Actions の watchdog は 8/26 まで success**（`gh run list`）。
  → **チャンネル側の異常ではなく、この回線から YouTube の RSS が引けないだけ。**
  watchdog は正常。ローカルで `watch_channel.py` を監視に使わないこと。
- **予約は 8/30 07:30 JST まで埋まっている**（6本）。**次の空き枠は 8/30 18:30 JST。**
- **題材の一次資料が取れた。** `evidence.collect('査証 手数料')` → 13件、
  先頭が `is_admissible: True`:

  ```
  speaker: 横山信一   第221回国会 参議院法務委員会 2026-05-28
  source : https://kokkai.ndl.go.jp/txt/122115206X01120260528/103
  quote  : …令和八年度予算では、外国人施策等の財源確保に向けて…査証手数料も
           引き上げることになっています。現状では一次有効査証の手数料は三千円ですが、
           一万五千円の大幅な引上げが予定されています。
           この査証手数料は一九七八年以来値上げされていない…いきなり五倍の値上げ…
  ```

  **見出しと引用の噛み合いは人（このセッション）が見て確認した。** 引用そのものに
  「3,000円→15,000円」「1978年以来」「五倍」が入っており、ニュースの事実と一致する。
  重複ガードも通る（`same-topic conflict: False`、候補ID `c099195dc5e4` は未使用）。

## 未検証のもの / できなかったこと

- **動画は作れていない。`ANTHROPIC_API_KEY` が無い。**
  - Bash・PowerShell の環境変数とも未設定（User スコープにも無し）。
  - `ant` CLI も未インストール、`~/.anthropic` も無し。
  - 実測: `Anthropic().messages.create(...)` →
    `TypeError: Could not resolve authentication method.`
  - `run_daily.py` は `write(recipe)` で `ScriptWriterUnavailable` を投げて
    **その場で日次実行を中止する**（設計どおり）。回避策は入れていない。
- VOICEVOX は起動済み（`/speakers` が 200）。詰まるのは台本生成だけ。
- `8ebRhoO41tM` の重複公開・再スケジュールの経緯は**推測**。ログは残っていない。
- `R_dirwcTjqs` が 26 再生に留まる理由は**不明**（配信制限か題材かは未確認）。

## 次にやること

1. **Anthropic の認証を用意する。** これが無いと1本も作れない。

   ```bash
   setx ANTHROPIC_API_KEY "sk-ant-..."
   ```

   （設定後は新しいシェルで実行すること）

2. **決めた題材で1本作る。** 次の空き枠 8/30 18:30 JST に入る。

   ```bash
   python scripts/run_daily.py --keyword "査証 手数料" --days-ahead 3 --limit 1
   ```

3. **本日 18:30 JST の `8ebRhoO41tM` をどうするか決める。** そのままだと
   1,461再生ある動画が再公開される。差し替えるなら:

   ```bash
   python scripts/unpublish.py 8ebRhoO41tM
   ```

4. **長尺の方針を決める。** 導線（関連動画38本）を張っても 2 再生だった。
   本数を増やす前に、題材かサムネイルか、どちらを測るかを決める。

5. **`zC8OJmUT9Us` を公開に戻すか消すか決める**（1,147再生あるが現在 private）。

## 触ってはいけないところ

- 採用ゲート（`evidence.collect()`）を緩めない。**認証が無いからといって
  台本生成を迂回する経路を足さない**（今回も足していない）。
- `state/*.json` を手で編集しない。
- **ローカルの `watch_channel.py` の 404 を「チャンネルが止まった」と読まない。**
  この回線から YouTube の RSS が引けないだけ。判定は GitHub Actions の watchdog を見る。
- 「関連動画」は API から読めない。設定したらその場で画面で確かめる。
- Studio を自動操作するときは、ダイアログが開いたのを見てから入力する
  （同一バッチで続けると説明文が壊れる。2026-08-26 の事故）。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする。
