# HANDOFF

最終更新: 2026-09-09（**この日に2つのセッションが走った**。
① 動画のBGMに自作曲を入れた（`main` に取り込み済み）
② **24時間ライブ配信の設計**（このブランチ。設計書のみ、コードは未着手））

## いま何をしているのか

**ニュースチャンネルで24時間のライブ配信を始める設計**を、ブランチ
`claude/live-streaming-setup-2cca36`（ワークツリー `video-content-research-60a976`）で進めている。

**設計書と実装計画は両方書き終わり、オーナーの承認も取れている。**

- 設計: [`docs/superpowers/specs/2026-09-09-live-streaming-design.md`](docs/superpowers/specs/2026-09-09-live-streaming-design.md)
- 計画: [`docs/superpowers/plans/2026-09-09-live-streaming.md`](docs/superpowers/plans/2026-09-09-live-streaming.md)（全10タスク）

**実装は1行も書いていない。** 次のセッションは **Task 1（前提の実測）から始める**。
実行方式（サブエージェント方式／このセッションで順に実行）は**未決**で、そこで止まっている。

**狙いは収益化要件の「有効な総再生時間4,000時間」**。実測でShortsルートが約97倍足りないのに対し、
4,000時間は平均同時視聴0.46人で届くと分かったため。

同じ日にBGMの作業（下記）が `main` に入っており、**このブランチはそれを取り込み済み**。

## ⚠ state がブランチ間で分裂している（未解決・known-issues 13番と同型）

**9/7〜9/11 の選挙動画5本は YouTube に予約済みなのに、`main` にも
このブランチの `state/published.json` にもエントリが無い。**
最新の state は **未 push のローカルブランチ
`claude/okinawa-governor-election-videos-d1ebd9`**（58件）にある。

```
main / claude/analytics-investigation-3eb248        51件（9/6まで）
claude/okinawa-governor-election-videos-d1ebd9      58件（9/11まで）★これが正しい
origin/claude/okinawa-governor-election-videos-d1ebd9  54件（9/7まで）
```

そのブランチには `scripts/check_telop.py`、`run_election.py` の修正、
`tests/test_election.py` の追加も入っている。**取り込もうとしたが `git merge` が拒否された。**
**チャンネルを動かす前に統合すること。**

## チャンネルの現況（2026-09-07 に API で確認。以降は未確認）

| 枠（JST） | video id | 状態 |
|---|---|---|
| 09-02〜09-06 18:30 | s0H-HHUiUfI / VqhHb3TfAgg / Ut919N6NctI / TXa3-6tCvkk / L2hB5naZk5o | public |
| 09-07〜09-11 18:30 | RhOoYz4TrpE / OfJk7NWKXTU / mxfqaTDzAYw / Md3w6Qaqx5Y / R3SZbpIoI5U | private・予約済み |
| 09-08 07:30 | My5mRImj744（相続税） | private・予約済み |

**9/8 以降に実際に公開されたかは未確認。**
予約を外した旧版が8本、非公開のまま残っている:
`vvpSRwF072M yHT9_jXuvlY BgIhdx43dSo -K_GQlJ4oR0 wL43dLccqLg phur61vle8A LOYwJw6tBUo BKwnK8HFczE`

---

# ① BGM（`main` に取り込み済み）

**全動画のナレーションの下に自作曲（`assets/bgm/petrichor.m4a`）を敷くようにした。**
音量の判定は感想ではなく **ffmpeg が書き出した音源の ebur128 実測値**で行う。
設計と地雷は `CLAUDE.md` の「BGM（自作曲）」節。

**まだ1本も投稿していない。** チャンネル上の動画は全部 BGM 無しの旧版のまま。
次に `run_daily.py` を回した動画から BGM が入る。

1. **`scripts/audio_mix.py`（新規）** — BGM を敷く**唯一の関門**。`mix(voice_wav, out_wav) -> MixReport`。
   - BGM のゲインは定数ではなく**実測から**決める（voice から 18 LU 下へ）。
   - 書き出した BGM を測り直し、**分離比が 15 LU を割ったら `NarrationBuried` で止める**（例外）。
   - 合成後に -14 LUFS へ、`alimiter` でピーク -1.0 dBFS。
2. **`build_short.py` / `build_long.py`** が `mix()` の出力を使う（TikTok は `build_short.build` 経由）。
3. **`assets/bgm/petrichor.m4a`** — `bgm-youtube` の `2026-08-21-petrichor` から5分を切り出し。
4. **cp932 の潜在バグを4箇所修正** — `subprocess.run(..., text=True)` に `errors="replace"`。

### BGM の検証済みの事実（実素材で1本焼いて測った）

| 測ったもの | 値 |
|---|---|
| ナレーション単体 | **-24.5 LUFS** |
| BGM（敷いた後） | **-42.5 LUFS** |
| **分離比** | **18.0 LU**（下限 15 LU） |
| 完成 mp4（AAC 後に独立測定） | **-14.1 LUFS / True Peak -1.0 dBFS** |
| 尺 | 58.43秒（BGM 無しの旧版と同一） |

**TuneCore の Content ID の申し立ては現に付いている**（動画は止まらないが広告収益が
TuneCore 側へ流れる）。**オーナーの判断でそのまま採用**（権利収入として戻るため）。

---

# ② ライブ配信の設計（このセッション）

## 今回やったこと

1. **チャンネルと収益化ルートを実測**（YouTube Data API + Analytics API v2）。
2. **YouTube公式ヘルプで2点を確認**（4,000時間の除外リスト／アーカイブの12時間上限）。
3. **配信APIとffmpegの前提を確認。**
4. **設計書を新規作成。** 自己レビューで2つの矛盾を直した
   （ffmpeg再起動とループ差し替えの両立／アーカイブ本数 730→760）。
5. **`main` の BGM 作業をマージし、設計の BGM 節を `audio_mix.mix()` を通す形に直した。**
6. **実装計画を作成**（`docs/superpowers/plans/2026-09-09-live-streaming.md`・全10タスク）。
   既存の `audio_mix.mix` / `narrate.synthesize` / `cards_wide.render_*` /
   `evidence.ground_excerpt` の**実シグネチャを読んでから**書いたので、
   計画中のコードはプレースホルダではない。
   セルフレビューで**仕様の1項目が全タスクから漏れていた**のを見つけて Task 10 を足した
   （`loop.mp4` の日次差し替え判定がどこにも無かった）。

## 検証済みの事実（実際に画面に出した出力）

```
channel: UCYHTfHJOoETzvpx-VZlUTng 日本の最新ニュースまるわかり
stats  : 登録者 2,910 / 動画 221本 / 総再生 1,341,662

=== 直近365日 ===
shorts             12,925.3 h   1,363,449 views
videoOnDemand           0.1 h           9 views

=== 直近90日 ===
shorts                789.3 h     103,169 views
videoOnDemand           0.0 h           5 views

liveBroadcasts.list OK   既存の配信枠: 0
ffmpeg version 9.0-full_build
```

- **スクショで開いていたチャンネルはニュースチャンネル本体**（`state/` 内271箇所で一致）。
- **収益化の2ルートの現在地**: Shorts 1,000万回/90日 に対し 103,169回（**約97倍足りない**）。
  総再生時間4,000時間に対し **0.1時間**。4,000 ÷ (365×24) = **平均同時視聴0.46人**。
- **YouTube公式ヘルプ**: 4,000時間に入らないのは 非公開・限定公開・削除済み・広告・**Shorts**・
  **「限定公開、削除済み、または VOD未変換のライブ配信」**。
  → **公開でアーカイブが残ったライブは加算される。**
- **同ヘルプ**: 「12 時間を超える配信については、アーカイブは作成されません」。
  → **切らずに垂れ流すと加算ゼロ。**
- **`work/` は8ディレクトリしか残っていない**（wav 7本・写真7枚）。
  **57件のレシピのうち50件は音声と写真が消えている**（テキストは全件残っている）。
- **レシピにナレーション原稿は入っていない**（キーは `id / headline / keyword / category / evidence`）。
  `evidence` は `kind / source_url / figure / quote / context / speaker`。
- **引用文は57件・中央値222字・合計10,564字。** `narrate.SECONDS_PER_CHAR = 0.171` で
  **1周およそ40分**。
- `cards_wide.py` に1920x1080の `render_headline / render_quote / render_telop / render_contents`
  が既にある。

## 未検証のもの

- **公開ライブのアーカイブが `videoOnDemand` として4,000時間に計上されるか。**
  ヘルプの除外リストに載っていないことからの**推定でしかない**。
  **ここが外れたら設計ごと破棄になる。実装より先に測る。**
- **ffmpegが流し続けている状態で、同じ再利用ストリームに次の枠をbindできるか。**
- **`-stream_loop -1` と `-c copy` の併用でループ境界のタイムスタンプが飛ばないか。**
- **チャンネルでライブ配信が実際に有効化されているか。** `liveBroadcasts.list` はAPIとしては
  通ったが、1本流すまで分からない。
- **平均同時視聴0.46人が取れるか。根拠は無い。**
- **`audio_mix.mix()` が40分の長い音源で通るか。** 58秒のショートでしか測っていない。
- **BGM 入りの動画が実際に投稿されたか。** まだ1本も出ていない。
- 9/8 以降の予約が公開されたか。
- TikTok の審査状況。

## 次にやること

1. **実行方式を決める**（サブエージェント方式／順に実行）。計画は
   `docs/superpowers/plans/2026-09-09-live-streaming.md`。
2. **Task 1（前提の実測）から始める。実装より先。**
   短い公開配信を1本流して終了し、(a) アーカイブが残るか
   (b) **3日後以降**に `videoOnDemand` の再生時間が増えるか、を見る。
   現在 0.1時間なので増えれば一目で分かる。
   **増えなければ Task 2 以降を全部破棄する**（設計が推定の上に乗っている）。

   ⚠ **Task 1 と Task 9 は公開ライブ配信を伴う。実行前にオーナーの承認を取ること。**
3. **予約した動画が公開されたか見る。** 事故があれば `python scripts/unpublish.py <video_id>`。
4. **`claude/okinawa-governor-election-videos-d1ebd9` を統合する**（上記 ⚠）。
5. **出典キャプションの改行を直す。** `recipes/` の発言系57件のうち**25件（44%）**で
   人名が行をまたいでいる（`cards._draw_source`）。直したら同じ57件を再描画して数える。
6. **`published.json` から `2D_cpARVcw0` のエントリを外す**（known-issues 8番の唯一の例外）。
7. **選挙が終わったら `scripts/election.py` / `run_election.py` / `tests/test_election.py` を消す。**
8. `com.-youtube` の Google OAuth トークンを失効・再発行する（持ち越し）。

## 触ってはいけないところ

### ライブ配信について（今回決めたこと）

- **既存ショートのループ配信をしない。** 公開済み動画の再利用配信は量産型ポリシーに正面から当たる。
- **採用ゲートをライブ経路に再実装しない。** 入力は `recipes/*.json` の出力だけ。
- **BGM の関門を新設しない。** `audio_mix.mix()` を通す。判定基準を2箇所に置かない。
- **ナレーション原稿をモデルに書かせない。** 読むのは見出し・逐語引用・出典の3つだけ。
- **写真を使わない。** 50件ぶん取り直しが要るうえ、人物写真の取り違えリスクを新経路に持ち込む。
- **12時間を超える配信をしない。** 超えた瞬間アーカイブが作られず、その配信の再生時間は
  1分も4,000時間に入らない。関門は `run_live.py` の枠を作る関数の中に置く。
- **投票日は選挙関連を外したループに差し替える**（公職選挙法129条）。
- **`state/live.json` を手で編集しない。**

### 既存（変わらず）

- **BGM の分離比の下限（`MIN_SEPARATION_LU = 15.0`）を下げない。**
- **数字を根拠に採用ゲートを緩めない。** 触ってよいのは `sources.PLUS`/`MINUS` と `keywords.POLICY` まで。
- **「採用ゲートを通ったか」で題材を選ばない。** 32語中31語が通る。引用を読んで人が見る。
- **`retention_report.py` の出力を、日別合計と突き合わせずに比較へ使わない**（known-issues 15番）。
- **タイトル・説明文は日本語。** 一度英語にして戻した経緯がある（2026-09-07）。
- **英語化を画面（テロップ・引用カード）と音声に広げない。** `ensure_grounded_card` が成立しなくなる。
- **`evidence.EVIDENCE_HOST_SUFFIX` を広げない。**
- **`election.MIN_PDF_CHARS` / `MIN_KANA_RATIO` を下げない。**
- **`build_short._fill` を「切り取らない」方式に変えない。** 顔が切れるのは `frame_photo.py` で直す。
- **`draw._BACKTRACK_RATIO` を下げすぎない。** 0.6 は実測158か所で決めた値。
- 台本ファイルの `source_url` / `source_quote` 必須をやめない。
- `state/*.json` を手で編集しない（`2D_cpARVcw0` の1件を除く）。
