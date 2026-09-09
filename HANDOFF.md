# HANDOFF

最終更新: 2026-09-09（**この日に4つの作業が走った**。
① 動画のBGMに自作曲を入れた（`main` 済み）
② 24時間ライブ配信の設計と実装計画
③ 実装（Task 2-8, 10 完了）
④ **Task 1（実測）に着手 → 実装のバグを発見して修正**）

## ⚠ 最初に読むこと: 実行して初めて出た欠陥が2つある（どちらも修正済み）

**テスト665件が通っていても、実際に走らせるまで両方とも見えなかった。**

### 1. mp4 が1本も焼けていなかった（`7514779`）

### 2. 公開配信が始まらなかった（403 invalidTransition・`4798882`）

`enableMonitorStream` の既定は `true` で、その場合 YouTube は
**testing 状態の経由を必須**にする。このデーモンは `ready` から `live` へ
直行するので、既定のままでは `transition` が拒否される。

```
HttpError 403 ... liveBroadcasts/transition?...&broadcastStatus=live
returned "Invalid transition" ... 'reason': 'invalidTransition'
```

公式ドキュメントで **「true なら testing を必須で経由 / false なら経由不可」**
を確認したうえで `monitorStream.enableMonitorStream = False` にした。

**設計の関門は正しく働いた**: `state/live.json` は書かれておらず、
ロックは残らなかった（`start_broadcast` は遷移が成功してから状態を書く）。

**⚠ 空の枠が1つ残っている**（一度も配信されていない。削除は未実施）:

```
lzt1loCYxWM  ready  public  monitor=True  ニュースラジオ 2026-09-09 08:35 UTC
```

---

### 1 の詳細: mp4 が1本も焼けていなかった

`build_live_loop.py` は**一度も mp4 を作れていなかった**。

```
Impossible to open 'work\live\parts\work/live/parts/000_00.png'
```

ffmpeg の concat は行内のパスを **concat ファイルが置かれている場所**から
解決するのに、cwd 基準の相対パスを書いていたので二重になっていた。
**テストが ffmpeg を偽物にしていたので 664件が通ったまま、レビュー4回も
すり抜けた。** 修正済み（`7514779`）。

**教訓**: 実素材で焼く検証（Task 5 Step 6-7）を飛ばしていたら、
**動かないコードで公開配信を始めていた。**

## いま何をしているのか

**ニュースチャンネルで24時間のライブ配信を出す機能**を、ブランチ
`claude/live-streaming-setup-2cca36` に実装した。**コードは書き終わっている。**

**オーナーの承認を得て Task 1（前提の実測）に着手した。** 基準値の記録・
ライブ配信の有効化確認・ループの作成までは済んだ。**公開配信は1度試して
403 で失敗し、原因（monitorStream）を直したが、修正後の再実行はしていない。**

- 設計: [`docs/superpowers/specs/2026-09-09-live-streaming-design.md`](docs/superpowers/specs/2026-09-09-live-streaming-design.md)
- 計画: [`docs/superpowers/plans/2026-09-09-live-streaming.md`](docs/superpowers/plans/2026-09-09-live-streaming.md)（全10タスク）
- 新規: `scripts/build_live_loop.py` / `scripts/run_live.py` と、その2つのテスト

**狙いは収益化要件の「有効な総再生時間4,000時間」。** Shorts ルートが約97倍
足りないのに対し、4,000時間は平均同時視聴0.46人で届くと実測で分かったため。

**⚠ 配信が最後まで通ったことは1度も無い。次にやるのは実装ではなく実測**（下記「次にやること」）。

## ⚠ state がブランチ間で分裂している（未解決・継続）

**9/7〜9/11 の選挙動画5本は YouTube に予約済みなのに、`main` にも
このブランチの `state/published.json` にもエントリが無い。**
最新は**未 push のローカルブランチ `claude/okinawa-governor-election-videos-d1ebd9`**（58件）。
そこには `scripts/check_telop.py`・`run_election.py` の修正・`tests/test_election.py` も入っている。
`git merge` が拒否された状態のまま。**チャンネルを動かす前に統合すること。**

---

# ③ ライブ配信の実装（このセッションの本題）

## 何を作ったか

```
recipes/*.json ──▶ build_live_loop.py ──▶ work/live/loop.mp4（16:9・約40分）
 (採用ゲート通過済み)   見出し・逐語引用・出典だけを読む
                       cards_wide で描画／audio_mix.mix() で BGM
                              │
                              ▼
                        run_live.py（常駐）
                  ffmpeg で RTMP へ流しっぱなし
                  11時間30分ごとに枠だけ差し替え
                  1日1回 loop.mp4 を作り直す
```

- **読み上げるのは `headline` / `evidence.quote`（逐語）/ `evidence.context` の3つだけ。**
  モデルが書いた文字列は1文字も入らない。`ANTHROPIC_API_KEY` 不要。
- **写真は使わない。** 引用カードを画面中央に置く。
- **BGM の関門は `audio_mix.mix()` 1箇所**（新設していない）。
- **配信は `-c copy`。** loop.mp4 側で h264+aac・2秒GOP まで作り切ってあるので、
  配信中の再エンコードが無く CPU をほとんど使わない。

## 検証済みの事実（実際に画面に出した出力）

### なぜライブなのか（2026-09-09・YouTube Data + Analytics API）

```
channel: UCYHTfHJOoETzvpx-VZlUTng 日本の最新ニュースまるわかり
stats  : 登録者 2,910 / 動画 221本 / 総再生 1,341,662

=== 直近365日 ===   shorts 12,925.3 h / 1,363,449 views  |  videoOnDemand 0.1 h / 9 views
=== 直近90日 ===    shorts    789.3 h /   103,169 views  |  videoOnDemand 0.0 h / 5 views
```

| ルート | 現在地 | 要件 | 差 |
|---|---|---|---|
| Shorts 1,000万回/90日 | 103,169回 | 10,000,000回 | **約97倍** |
| 有効な総再生時間 4,000時間 | **0.1時間** | 4,000時間 | 平均同時視聴 **0.46人**を1年 |

**YouTube公式ヘルプで確認**: 4,000時間に入らないのは 非公開・限定公開・削除済み・
広告・**Shorts**・**「限定公開、削除済み、または VOD未変換のライブ配信」**。
→ **公開でアーカイブが残ったライブは加算される。**
同ヘルプ: **「12 時間を超える配信については、アーカイブは作成されません」**。
→ **切らずに垂れ流すと加算ゼロ。** これが11時間30分で切る設計の理由。

### Task 1（実測）でここまでに確定したこと

**基準値（3日後にこれと比べる）** — 2026-09-09 測定、範囲 2025-09-09〜2026-09-09:

```
shorts               12925.28 h  1,363,449 views
videoOnDemand            0.08 h          9 views     ← これが増えるかを見る
stats: 登録者 2,910 / 動画 221本 / 総再生 1,341,662
```

**ライブ配信は有効だった**（未検証項目が1つ解消）。公開せずに取り込み口だけ
作って確認した:

```
✓ ストリームを確保: id=YHTfHJOoETzvpx-VZlUTng1788938418542783
  streamStatus: ready
  ingest      : rtmp://a.rtmp.youtube.com/live2
```

**公開時に出るもの**（`run_live.py` の実装を読んで確認）:
タイトル `ニュースラジオ YYYY-MM-DD HH:MM UTC` / `privacyStatus: public` /
`selfDeclaredMadeForKids: false`。**登録者2,910人に通知が飛ぶ。**

**concat の修正後、mp4 が実際に焼けることを確認した**（5題材の実測用ループ）:

```
- 除外 election: 5件          ← 除外の関門が実データで効いた
- 除外後 52件 → 先頭 5件で実測用ループを作る
✓ work\live\loop.mp4

duration=239.533333   size=14580075
codec_name=h264  width=1920  height=1080  r_frame_rate=30/1
codec_name=aac   sample_rate=48000
```

5題材で239.5秒 = **1題材あたり47.9秒**。52題材なら約2,490秒（41.5分）で、
設計書の窓（2,000〜2,900秒）に入る。**ただし全57件を通しで焼いた実測ではない。**

`python scripts/run_live.py --dry-run` も通った（レシピ57件・除外なし・
ループ動画のパスを表示、公開しない）。

**⚠ 公開配信の開始は自動承認の分類器にブロックされる。** 迂回はしていない。
オーナーが手で実行するか、`python scripts/run_live.py` を許可する Bash ルールを
設定に足す必要がある。**2026-09-09 はオーナーが手で実行し、403 invalidTransition
で失敗した**（上記の欠陥2）。修正後の再実行はまだ行っていない。

### レビューが見つけた重大な欠陥（修正済み）

- **投票日の選挙除外が丸ごと効いていなかった。** 実測:

  ```
  recipes の category: {'政治': 52, 'election': 5}
  run_election.py:143 が "election" / run_daily.py:492 が "政治" を書く
  ```

  計画・設計書・テストがすべて使っていた **`"選挙"` は0件にしか当たらない**。
  投票日に `--exclude-category 選挙` を打っても57件そのままだった。さらに
  日次リビルドが除外指定を渡していなかったので、正しく作った投票日ループも
  次のローテーションで上書きされていた。公選法129条の唯一の安全装置が
  両方向に黙って失敗していた。
  → **除外が1件も当たらなければ例外で止まる**ようにし、除外指定を
  デーモンに通した。テストも実在する値 `election` に直した。
- **引用カードの57件中38件が画面からはみ出していた。** 引用の中央値222字に対し
  `render_quote` は6行（約165字）まで。ナレーションは全文を読むので、
  配信の大半で「聞こえている文が画面に無い」状態だった。
  → **文の境界で複数フレームに分割**し、尺を字数比で配分した。
  実測で **38/57 → 0件**、フレーム構成は {1枚:19, 2枚:37, 3枚:1}。
  各フレームの文字列は引用の**連続した部分文字列**のままで、
  つなぐと元の引用に戻ることをテストで縛ってある。
- **起動直後に `start_broadcast` を呼んでいて、初回はほぼ確実に失敗する**
  （YouTube は `streamStatus == "active"` を要求する）。しかもその失敗経路が
  `finally` を通らず、**ffmpeg が ingest キーに流しっぱなしで残る**。
  → active になるまで待ってから遷移し、起動窓の後始末で ffmpeg を止めるようにした。
- **ローテーションの再試行に諦め時が無く、30分の余裕を使い切ると12時間を超えて
  アーカイブが丸ごと消える**（修正前は11時間30分で確定できていた）。
  → `HARD_LIMIT - 5分` で諦めて枠を確定させる。

## テストの状況

着手前は 630（BGM 作業まで）→ 実装後 **664 passed**（画面に出して確認済み）。
そのあと実行して見つけた欠陥2件に回帰テストを1件ずつ足した:

- concat のパス: `tests/test_build_live_loop.py` **33 passed**
- monitorStream: `tests/test_run_live.py` **32 passed**

**全件の再実行は走らせたが、このファイルを書いた時点で結果を確認していない。**
確認するまで「全部通った」と書かないこと。

## 未検証のもの

- **公開ライブのアーカイブが `videoOnDemand` として4,000時間に計上されるか。**
  ヘルプの除外リストに載っていないことからの**推定でしかない**。
  **これが外れたらこの機能は丸ごと無意味。実装より先に測る（Task 1）。**
- **全57件のループは1度も焼き切れていない。「1周およそ40分」は
  5題材の実測（1題材47.9秒）からの外挿。**
- **`ready → live` の直行が実際に通るかは未検証。** monitorStream を無効に
  する修正は入れたが、**修正後に配信を試していない。** ここは実行しないと
  分からない唯一の点。
- **配信が最後まで通ったことは1度も無い。** 2026-09-09 の実行は枠の作成・
  bind・ストリームの active 待ちまでは通り、live への遷移で落ちた。
  差し替え（ローテーション）と ffmpeg の実配信は未実行。
  `_run_forever` のループ本体にはテストが無い（純関数はテストで縛ってある）。
- **ffmpeg が流し続けている状態で同じストリームに次の枠を bind できるか**は未確認。
- **`-stream_loop -1` と `-c copy` のループ境界でタイムスタンプが飛ばないか**も未確認。
- **平均同時視聴0.46人が取れるか。根拠は無い。**
- **tick の長さが60秒に固定でない**（`wait_for_stream_active` が最大300秒
  ブロックしうる）。レビューアの追跡では、その経路に入る時点で古い枠の
  アーカイブは既に確定しているので実害は例外の種類だけ。**保留。**
- **BGM 入りの動画がまだ1本も投稿されていない**（②の作業）。
- 9/8 以降の予約が公開されたか。TikTok の審査状況。

## 次にやること

1. **修正後のループが焼けたか確認する。**

   ```bash
   ffprobe -v error -show_entries format=duration,size -of default=nw=1 work/live/loop.mp4
   ```

   焼けていなければ concat の修正がまだ足りない。**ここが通るまで配信しない。**

2. **Task 1 の続き: 公開配信を1本流す。** ⚠ **オーナーは 2026-09-09 に承認済み。**
   **私（Claude）が実行しようとすると分類器に止められる。** オーナーが手で打つか、
   許可ルールを足すこと。ループが焼けていることを確認してから:

   ```bash
   python scripts/run_live.py --dry-run            # 材料の確認
   python scripts/run_live.py                      # 公開配信を開始（バックグラウンド）
   # …約15分…
   python scripts/run_live.py --stop               # 枠を終了してアーカイブを確定
   # デーモンのプロセスも止めること（--stop はプロセスを終わらせない）
   ```

   そのあと `liveBroadcasts.list(broadcastStatus="completed")` でアーカイブが
   残ったかを見る。**アーカイブは消さないこと**（消すと再生時間もゼロになり
   測定が成立しない）。

3. **3日後（2026-09-12以降）に基準値と比べる。**
   `videoOnDemand` が **0.08 h から増えていること**。
   **増えなければこの機能は丸ごと破棄する。**

4. **Task 9: 実配信で未検証3点を潰す。** ⚠ **これも公開配信。**
   `ROTATE_AFTER` を一時的に数分にして枠の差し替えとループ境界を見る。

5. **全57件のループを焼いて尺を測る。** 2,000〜2,900秒に入っていること。

6. **空の枠 `lzt1loCYxWM` を消すか決める。** 一度も配信されていないが `public`
   なので、チャンネルに予定配信として並びうる。削除は取り消せないので保留中。

7. **`claude/okinawa-governor-election-videos-d1ebd9` を統合する**（上記 ⚠）。

8. **出典キャプションの改行を直す。** `recipes/` の発言系57件のうち**25件（44%）**で
   人名が行をまたいでいる（`cards._draw_source`）。直したら同じ57件を再描画して数える。

9. **`published.json` から `2D_cpARVcw0` のエントリを外す**（known-issues 8番の唯一の例外）。

10. **選挙が終わったら `scripts/election.py` / `run_election.py` / `tests/test_election.py` を消す。**

11. `com.-youtube` の Google OAuth トークンを失効・再発行する（持ち越し）。

## 触ってはいけないところ

### ライブ配信

- **12時間を超える配信をしない。** 超えた瞬間アーカイブが作られず、その配信の
  再生時間は1分も4,000時間に入らない。`ROTATE_AFTER`（11h30m）/
  `ROTATION_GIVE_UP_AFTER`（11h55m）/ `HARD_LIMIT`（12h）を動かさない。
- **二重起動の関門を `start_broadcast` の外に出さない。** 呼び出し側に置いた穴が
  このプロジェクトで3回開いている。
- **採用ゲートをライブ経路に再実装しない。** 入力は `recipes/*.json` の出力だけ。
- **BGM の関門を新設しない。** `audio_mix.mix()` を通す。
- **ナレーション原稿をモデルに書かせない。** 見出し・逐語引用・出典の3つだけ。
- **引用カードに載せる文字列を引用の連続した部分文字列から外さない。**
  分割はしてよいが、言い換え・省略記号の挿入はしない。
- **写真を使わない。**
- **投票日は `--exclude-category election` を付ける。** 値は `"選挙"` ではない。
- **`state/live.json` を手で編集しない。** 事故ったら `python scripts/run_live.py --stop`。
- **concat ファイルにパス付きの行を書かない。** ffmpeg は concat ファイルの
  ある場所から解決するので二重になる。ファイル名だけを書く（2026-09-09 実測）。
- **ffmpeg を偽物にしたテストだけで「焼ける」と判断しない。**
  664件が通ったまま mp4 が1本も焼けていなかった。実素材で1本焼くこと。
- **`monitorStream.enableMonitorStream` を true に戻さない。** 既定は true で、
  その場合 testing 状態の経由が必須になり、ready から live への直行が
  403 invalidTransition で拒否される（2026-09-09 実測）。
- **API を叩く経路は、偽物のクライアントでテストしても「通る」と言えない。**
  枠の作成・bind・遷移はどれも実際に叩くまで分からなかった。

### 既存（変わらず）

- **BGM の分離比の下限（`MIN_SEPARATION_LU = 15.0`）を下げない。**
- **数字を根拠に採用ゲートを緩めない。** 触ってよいのは
  `sources.PLUS`/`MINUS` と `keywords.POLICY` まで。
- **「採用ゲートを通ったか」で題材を選ばない。** 32語中31語が通る。
- **`retention_report.py` の出力を、日別合計と突き合わせずに比較へ使わない**（15番）。
- **タイトル・説明文は日本語。** 一度英語にして戻した経緯がある（2026-09-07）。
- **英語化を画面と音声に広げない。** `ensure_grounded_card` が成立しなくなる。
- **`evidence.EVIDENCE_HOST_SUFFIX` を広げない。**
- **`election.MIN_PDF_CHARS` / `MIN_KANA_RATIO` を下げない。**
- **`build_short._fill` を「切り取らない」方式に変えない。**
- **`draw._BACKTRACK_RATIO` を下げすぎない。** 0.6 は実測158か所で決めた値。
- 台本ファイルの `source_url` / `source_quote` 必須をやめない。
- `state/*.json` を手で編集しない（`2D_cpARVcw0` の1件を除く）。

---

# ① BGM（`main` 済み・変更なし）

全動画のナレーションの下に自作曲（`assets/bgm/petrichor.m4a`）を敷く。
`scripts/audio_mix.py` の `mix()` が唯一の関門で、**分離比が 15 LU を割ったら
`NarrationBuried` で止まる**。実測: ナレーション -24.5 LUFS / BGM -42.5 LUFS /
分離比 18.0 LU / 完成 mp4 -14.1 LUFS・True Peak -1.0 dBFS。

**まだ1本も投稿していない。** 次に `run_daily.py` を回した動画から BGM が入る。
TuneCore の Content ID の申し立ては現に付いているが、**オーナーの判断で
そのまま採用**（権利収入として戻るため）。
