# HANDOFF

最終更新: 2026-09-10（セッション: **アナリティクスを全期間で調べ直し、その所見を
実際に取り込んだ**。`docs/analytics-2026-09-10.md` を追加し、CLAUDE.md に
「チャンネルの現在地」を置き、**分裂していた state を統合**し、
`docs/daily-workflow.md` に朝の枠の埋め方を書いた。
**チャンネルへの投稿・変更は一切していない**）

## 今回やったこと（すべて `main` 済み・pytest 668 passed）

1. **アナリティクスの全期間調査** → `docs/analytics-2026-09-10.md`
2. **所見を CLAUDE.md に恒久化** → 「チャンネルの現在地 — 施策を提案する前に踏まえること」
3. **分裂していた state を統合**（下記）
4. **朝の枠が空く原因を特定し、手順を書き換えた** → `docs/daily-workflow.md`
5. **冒頭の維持率を上げる設計書を書いた**（実装はしていない）
   → `docs/superpowers/specs/2026-09-10-opening-retention-design.md`

## ✅ state の分裂は解消した（旧「⚠ state がブランチ間で分裂している」）

`main`（52件）と `claude/okinawa-governor-election-videos-d1ebd9`（58件）は
**どちらも他方の上位集合ではなかった**。共通51キーは中身まで一致していたので
**和集合59件**で解決した。`check_telop.py`・`run_election.py` の修正・
`tests/test_election.py` も取り込んだ（commit `36818f5`）。

**YouTube API と突き合わせて検証済み:**

- 59件中58件は実在。**`2D_cpARVcw0` だけ存在しない**（known-issues 8番の既知の1件。
  外す作業は未実施）
- 予約中は **09/10 18:30 `Md3w6Qaqx5Y`** と **09/11 18:30 `R3SZbpIoI5U`** の2枠だけ
- **`publish_at` を持たない private が8本チャンネル上に残っている**
  （`BKwnK8HFczE` `LOYwJw6tBUo` `phur61vle8A` `-K_GQlJ4oR0` `BgIhdx43dSo`
  `yHT9_jXuvlY` `wL43dLccqLg` `vvpSRwF072M`）。すべて公開済みの選挙動画と
  タイトルが重複し、9/2 の 15:38〜16:16 に上がっている。**枠は塞いでいない**
  （`taken_slots()` は `publish_at` のあるものだけ見る）。削除は取り消せないので保留

## 朝(07:30)の枠が空く原因 — 特定済み

`pending_slots` は過ぎた枠を遡って埋めない（`scripts/slots.py`）。
**07:30 の枠を作れるのは 07:30 より前に走ったときだけ。18:30 は一日じゅう作れる。**
自動実行は 2026-08-18 に削除済みで、セッションは日中〜夕方に立ち上がるので、
**素の実行を続ける限り 07:30 は構造的に空く。**

- 実測: 2026-08-20〜09-09 の42枠で**空いたのは 09/03・09/04・09/07 の 07:30 だけ**。
  18:30 は1枠も空いていない
- **歩留まりは原因ではない**（2026-09-10 実測: 採用ゲート 20件中14件通過、
  最上位の通過候補は2番目）
- **認証も無い**: `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ant` プロファイルは
  いずれも未設定（実測）。素の `run_daily.py` は `ScriptWriterUnavailable` で即停止する

**→ 決めた手順: セッションを終える前に翌日分を作る。**

```bash
python scripts/run_daily.py --days-ahead 1 --limit 1   # 翌日 07:30
python scripts/run_daily.py --days-ahead 1 --limit 1   # もう一度で翌日 18:30
```

**⚠ 9/11 の 07:30 はまだ空いている**（18:30 は `R3SZbpIoI5U` で予約済み）。

## 2026-09-10 に確定した数字（API 実測・`docs/analytics-2026-09-10.md`）

**ライブ配信に賭ける判断の根拠が、数字の側から補強された。**

- **ショートの寿命は約14日で、15日目にゼロになる。** 直近7日の再生を経過日数で
  束ねると 0-7日=11,673 / 8-14日=1,674 / 15-21日=**6** / 22-30日=**15**。
  2026年1〜7月（投稿ゼロ）に月2,200〜3,900へ落ちた事実と整合する。
  **再生数 ≒ 本日の投稿本数 × 約1,300。バックカタログの価値はゼロ。**
- **収益化ルートA（ショート1,000万回/90日）は算術的に閉じている。**
  直近90日 105,761回 = 要件の 1.06%（**94.6倍**足りない）。
  1本1,344回で埋めるには**1日82.7本**。最盛期の1本5,454回で計算しても1日20本。
- **ルートB（4,000時間/365日）だけが残る。** 必要なのは 1日10.96時間。
  ショートはすでに **1日25.4時間**の再生時間を生んでいる（箱が違うだけで総量は2.3倍ある）。
  → **Task 1（2026-09-12 の測定）がチャンネルの分岐点。** 変わらず最優先。
- **登録者2,910人は要件1,000人を満たしている。登録者は伸ばす対象ではない。**
  登録者からの再生は 1,918（全体の1.9%）。
- 平均視聴率の中央値は **2025年10月 95.3% → 2026年8月 69.0%**。再生数の差4.1倍は
  当時の需要と交絡するが、**維持率の差は題材では説明が付かない**（同じ尺・同じ縦型）。
  30日窓 n=51 で r(維持率, 再生数) = **0.65**。上位半分1,776 / 下位半分1,263。
- 検索（全体の3.2%）だけが**14日で腐らない面**。検索語は
  「106万の壁 撤廃」220 /「生活道路 30km」129 /「古謝玄太」127 /「2026年10月 社会保険」92。
  **長尺 `UqjB--sNTKk`（生涯5再生）はこのどれにも当たらない題材だった。**
  「長尺に面が無い」ではなく「検索需要のある題材で長尺を試していない」が正確。
- 計測の健全性は確認済み: 30日窓で day_sum = video_sum = 101,250（差0）。

**⚠ BGM は次の `run_daily.py` から入る。** 音が全動画で変わるので、
**その前後をまたぐ維持率の比較は交絡する。** 比較するなら BGM 導入日をまたがない窓で。

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

**修正後の再実行で配信が通り、アーカイブまで残った（2026-09-09）:**

```
wWGQuS3yfXc  complete  public  ニュースラジオ 2026-09-09 09:11 UTC
  uploadStatus : uploaded      duration : PT14M41S
  actualStart  : 2026-09-09T09:12:07Z
  actualEnd    : 2026-09-09T09:26:48Z
  URL          : https://www.youtube.com/watch?v=wWGQuS3yfXc

lzt1loCYxWM  ready  public  monitor=True   ← 失敗した空の枠（未削除）
```

**このアーカイブは消さないこと。** 消すと再生時間もゼロになり、3日後の測定が
成立しない。

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

**Task 1（前提の実測）の配信部分が完了した。** 2026-09-09 に14分41秒の
公開配信を行い、**アーカイブが `public` の動画として残ることを確認した**
（`wWGQuS3yfXc`）。デーモンと ffmpeg は停止済み、`state/live.json` も
`live: false` でクリーン。

**残るは3日後（2026-09-12以降）の測定だけ。** これが Task 1 の結論になる。

- 設計: [`docs/superpowers/specs/2026-09-09-live-streaming-design.md`](docs/superpowers/specs/2026-09-09-live-streaming-design.md)
- 計画: [`docs/superpowers/plans/2026-09-09-live-streaming.md`](docs/superpowers/plans/2026-09-09-live-streaming.md)（全10タスク）
- 新規: `scripts/build_live_loop.py` / `scripts/run_live.py` と、その2つのテスト

**狙いは収益化要件の「有効な総再生時間4,000時間」。** Shorts ルートが約97倍
足りないのに対し、4,000時間は平均同時視聴0.46人で届くと実測で分かったため。

**⚠ 次にやるのは実装ではなく2026-09-12以降の測定**（下記「次にやること」）。

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

全件の再実行を画面に出して確認した:

```
666 passed in 205.60s (0:03:25)
```

**既存のテストは1件も落ちていない。**

## 未検証のもの

- **公開ライブのアーカイブが `videoOnDemand` として4,000時間に計上されるか。**
  ヘルプの除外リストに載っていないことからの**推定でしかない**。
  **これが外れたらこの機能は丸ごと無意味。実装より先に測る（Task 1）。**
- **全57件のループは1度も焼き切れていない。「1周およそ40分」は
  5題材の実測（1題材47.9秒）からの外挿。**
- **アーカイブが `videoOnDemand` として4,000時間に計上されるかは未検証。**
  アーカイブが残ることまでは確認した。**計上されるかが Task 1 の本題で、
  2026-09-12 以降にしか分からない。**
- **配信の健全性が `bad` だった。** `healthStatus: bad | error: Video output low`。
  中身が静止画なのでビットレートが約487kbps しか出ず（14.5MB ÷ 239.5秒）、
  YouTube が 1080p30 に期待する 4,500kbps を大きく下回る。
  **アーカイブは問題なく作られた**ので実害は未確認。直すなら
  `build_live_loop.py` の ffmpeg に `-minrate`/`-maxrate`/`-bufsize` を足す。
  **計上されるかを確かめる前に直さないこと**（変数が増える）。
- **差し替え（ローテーション）は未実行。** 11時間30分たたないと起きないので、
  Task 9 で `ROTATE_AFTER` を短くして確かめる必要がある。
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

0. **翌日の枠を埋める。** 9/11 の 07:30 が空いている（上記）。
   題材は `yield_report.py --refresh` で見て `--only` で選ぶ。
   台本は対話セッションが書いて `--script` で渡す（認証が無いので素では動かない）。

1. **2026-09-12 以降に基準値と比べる。これが Task 1 の結論。**

   ```bash
   python -c "
   import sys, datetime; sys.path.insert(0,'scripts')
   from upload_youtube import get_credentials
   from googleapiclient.discovery import build
   an = build('youtubeAnalytics','v2',credentials=get_credentials())
   end = datetime.date.today(); start = end - datetime.timedelta(days=365)
   r = an.reports().query(ids='channel==MINE', startDate=str(start), endDate=str(end),
       metrics='estimatedMinutesWatched,views', dimensions='creatorContentType').execute()
   for row in r.get('rows', []): print(f'{row[0]:18} {row[1]/60:9.2f} h {row[2]:>10,} views')
   "
   ```

   **基準値は `videoOnDemand 0.08 h / 9 views`（2026-09-09 測定）。**
   増えていれば設計の前提が正しい。**増えなければこの機能は丸ごと破棄する。**

2. **Task 9: ローテーションとループ境界を確かめる。** ⚠ 公開配信。
   `ROTATE_AFTER` を一時的に数分にして `run_live.py` を回し、
   (a) ffmpeg を止めずに次の枠へ差し替えられるか
   (b) `-stream_loop -1` と `-c copy` のループ境界で映像・音声が飛ばないか
   を見る。終わったら `ROTATE_AFTER` を戻してテストを通すこと。

3. **配信の健全性（`Video output low`）を直すか決める。**
   **1 の結果が出るまで触らない。**

4. **全57件のループを焼いて尺を測る。** 2,000〜2,900秒に入っていること。
   5題材の実測（1題材47.9秒）からの外挿では約2,490秒。

5. **空の枠 `lzt1loCYxWM` を消すか決める。** 一度も配信されていないが `public`
   なので、チャンネルに予定配信として並びうる。削除は取り消せないので保留中。

6. **`claude/okinawa-governor-election-videos-d1ebd9` を統合する**（上記 ⚠）。

7. **出典キャプションの改行を直す。** `recipes/` の発言系57件のうち**25件（44%）**で
   人名が行をまたいでいる（`cards._draw_source`）。直したら同じ57件を再描画して数える。

8. **`published.json` から `2D_cpARVcw0` のエントリを外す**（known-issues 8番の唯一の例外）。

9. **選挙が終わったら `scripts/election.py` / `run_election.py` / `tests/test_election.py` を消す。**

10. `com.-youtube` の Google OAuth トークンを失効・再発行する（持ち越し）。

11. **冒頭の維持率の A/B に着手するか決める。** 設計書は書いてある
    （`docs/superpowers/specs/2026-09-10-opening-retention-design.md`）。
    **1 の結果が出るまで着手しない。** ライブが通ればショートの優先度は下がる。

12. **`publish_at` の無い private 8本を消すか決める。** 枠は塞いでいないので急がない。
    削除は取り消せない。

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
- **`liveBroadcasts.list` に `mine` と `broadcastStatus` を同時に渡さない。**
  400 `incompatibleParameters` になる。`broadcastStatus` 単独で自分の枠が返る。
- **`wWGQuS3yfXc`（2026-09-09 の実測配信のアーカイブ）を消さない。**
  消すと再生時間もゼロになり、Task 1 の測定が成立しない。

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
