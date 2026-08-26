# HANDOFF

最終更新: 2026-08-26（セッション: アカウント調査）

## いま何をしているのか

「アカウントを調査してください」の依頼で、**チャンネル・認証・予約在庫・指標を
外から実測した**。動画は作っていない。チャンネルへの書き込み操作もしていない
（叩いたのは読み取り API だけ）。

結論は2つ。

1. **チャンネルは正常に動いている。** 8/26 07:30 まで途切れなく公開され、
   8/30 07:30 までの予約8本も YouTube 側で正しく入っている（API で実測）。
2. `token.json` が `invalid_grant` で死んでいた → **同日中に復旧済み**。
   `--auth-only` が同意画面に落ちてこない不具合も直した。
   詳細は `docs/known-issues.md` **14番**。
   **ただし同意画面の公開ステータスは未確認で、「テスト中」のままなら
   2026-09-02 ごろにまた失効する。**

## 今回やったこと

- `python scripts/upload_youtube.py --auth-only` → **失敗**（下記）
- `python scripts/watch_channel.py --within 14` → 成功
- 公開RSS（`feeds/videos.xml`）を直接引いて公開済み15本を一覧
- **生きている方のトークン**（`.claude/worktrees/video-content-research-60a976/`）で
  読み取り API を実行し、`state/published.json` の全40件の実 status を引き直した
- `youtubeAnalytics` で直近30日・90日・365日の指標を取得した
- `docs/known-issues.md` に **14番**（トークン失効）を追記した
- Windows タスクスケジューラを検索 → **このプロジェクトのタスクは無い**

## 検証済みの事実（実際に画面に出した出力）

### 認証：2つ目の OAuth クライアントだけが死んでいる

```
google.auth.exceptions.RefreshError:
  ('invalid_grant: Token has been expired or revoked.', ...)
```

- 落ちるのは `upload_youtube.py:92`（`get_service()` の `creds.refresh`）。
  クォータ超過のときのような案内は出ず、素の traceback が出る。
- リポジトリ直下と `research-and-video-ede9c9` の `token.json` は
  **md5 が一致**（client `639758631694-…`、8/19 発行）→ どちらも死んでいる。
- `.claude/worktrees/video-content-research-60a976/token.json` は
  **別クライアント**（`393077911026-…`、8/10 発行）で、**生きている**:
  `✓ 認証しました: 日本の最新ニュースまるわかり（UCYHTfHJOoETzvpx-VZlUTng）`
- → アカウントの失効ではなく、8/19 に作った2つ目の GCP プロジェクト側の問題。
  発行 8/19 01:58 UTC → 8/26 で**ちょうど7日**。同意画面が「テスト中」の
  クライアントは7日でリフレッシュトークンが失効する仕様に一致する
  （**Console 側は未確認**。known-issues 14番）。

### チャンネルは止まっていない

`watch_channel.py --within 14`:
`✓ 直近14日に 15本 公開されています（最新: 2026-08-26 07:30 「みんな忘れている」再エネ賦課金の出発点は月88円だった）`

### 予約在庫（`videos.list` で実測。HANDOFF の旧「未検証」を解消）

`state/published.json` の40件を API で引き直した結果:

- **8/26 18:30〜8/30 07:30 の8本すべて `private` + `publishAt` が state と完全一致。**
  二重予約なし・欠落なし。

  | 枠 | videoId | 題材 |
  |---|---|---|
  | 8/26 18:30 | CXdd3ODNGqk | レアアース輸出規制 |
  | 8/27 07:30 | XW392Sr9Zew | 攻めの農業＝輸出 |
  | 8/27 18:30 | 8ebRhoO41tM | 日本ベルギー外交160周年 |
  | 8/28 07:30 | NFjiJ0U54ZI | 最低賃金と働き控え |
  | 8/28 18:30 | xNkyuxioRJk | ガソリン G7最安水準 |
  | 8/29 07:30 | hMJkj8UMZjg | 奨学金 四人に一人 |
  | 8/29 18:30 | -4cbnhI5wVA | 出産費用無償化 |
  | 8/30 07:30 | EBnFdZpSwsc | 参政党 60〜70点 |

- 過去分はすべて `public`。8/25 07:30 空き家・8/25 18:30 介護職・8/26 07:30 再エネと、
  8/20 に移した先の枠どおりに公開されている（13番の解消を実測で確認）。
- `2D_cpARVcw0` のみ **NOT FOUND**（Studio で手動削除した残骸。known-issues 8番に既記載）。
- `zC8OJmUT9Us`（憲法審査会）は `private`・予約なし＝使わない在庫のまま。
- **次の空き枠は 8/30 18:30。**

### チャンネル指標

- 登録 **2,880** / 総再生 **1,321,830** / 動画 **196本**（チャンネル開設 2025-09-24。
  パイプライン産は `published.json` の40件ぶんだけ）
- `status.isChannelMonetizationEnabled: **false**`
- 直近30日（7/27〜8/23、Analytics は2日ほど遅れる）:
  **64,084 再生 / 530時間 / 登録 +47 −14 = 純+33**
- **8/12 を境に日次 ~80再生 → 4,000〜10,000再生に跳ねている**（パイプライン稼働の効果）
- 最高: `C5_poVw8hlM`（食料品の消費税1%で減収4.3兆円）**14,334再生・151いいね**
- 種別内訳:
  - 直近365日: Shorts **1,327,670再生 / 12,696時間**、長尺 **4再生 / 0時間**
  - 直近90日: Shorts **68,407再生**（長尺の行は出ない）
- **8/20 に追加した長尺1本目 `UqjB--sNTKk`（4分15秒・公開）は 6日間で 0再生・0いいね。**

### 自動化

- タスクスケジューラにこのプロジェクトのタスクは**存在しない**
  （`Get-ScheduledTask` で該当なし）→ 実行はすべて手動。
- `.github/workflows/watchdog.yml` は公開RSSだけを見る。
  **認証の失効は在庫が尽きるまで検知できない**（今回の在庫は 8/30 07:30 まで
  あるので、7日窓の通知は 9/6 ごろ）。

## 未検証のもの

- **Google Cloud Console の同意画面の公開ステータス**（「テスト中」か「本番」か）。
  7日失効の説明はこれで整合するが、Console を見ていないので**推定のまま**。
  **切り替えていなければ 2026-09-02 ごろに再び `invalid_grant` になる。**
  確認先: Google Cloud Console → プロジェクト（`639758631694-…` の方）→
  「API とサービス」→「OAuth 同意画面」→ 公開ステータス。
- 予約8本の「見出しと引用が噛み合っているか」の**人手**確認。
  8/20 のセッションで AI の下見はしているが、人は見ていない。
- 長尺が0再生である理由（サムネイル・題材・アルゴリズム）は調べていない。
- 収益化要件の充足状況は Studio で確認していない（API の `false` を見ただけ）。

## 次にやること

1. **同意画面が「テスト中」なら「本番」に切り替える**（Console 側・未確認）。
   切り替えないと 2026-09-02 ごろにまた失効する。
   失効したときの復旧はこれで通る（消さなくてよい）:

   ```bash
   python scripts/upload_youtube.py --auth-only
   ```

2. 公開時刻前に、予約8本の見出しと引用の噛み合いを**人が**見る（README の運用ルール）。
3. 認証が戻ったら 8/30 18:30 以降を埋める。`--days-ahead` は「N日後の枠だけ」を指すので、
   順に埋めるなら N を日ごとに指定する。

   ```bash
   python scripts/run_daily.py --limit 1 --days-ahead 4
   ```

4. 長尺（18:00枠）を続けるかを決める。1本目が0再生なので、
   続けるなら「なぜ0なのか」を測ってから。判断材料が無いまま本数だけ増やさない。

## 今回やったこと（追記：2026-08-26 の同一セッション）

調査後、人が `--auth-only` を叩いたところ**同じ traceback で落ちた**ので、原因を追った。

- `get_service()` は `creds.refresh()` の例外でそのまま抜けるため、**すぐ下の
  同意画面フロー（`run_local_server`）に落ちてこない**。つまり
  `--auth-only` では失効を復旧できない状態だった。
- `RefreshError` を握って理由を表示してから同意画面へ落とすように
  [`scripts/upload_youtube.py`](scripts/upload_youtube.py) を修正した。
  握るのは `RefreshError` だけなので、通信不能とクォータ超過は今までどおり素通し。
- 先にテストを書いて落ちることを確認してから直した（`tests/test_upload_youtube.py`）:
  - `test_失効したtokenは同意画面をやり直す`
  - `test_生きているtokenは同意画面をやり直さない`
- **`pytest` 414 passed**（全件・実出力）。
- 副作用: 無人実行中に失効するとブラウザ待ちで**止まる**（以前は即クラッシュ）。
  `token.json` が無いときの挙動は元からこれなので新しい穴ではない。
### 認証の復旧（2026-08-26 13:08 JST・実測）

人が直下で `--auth-only` を実行し、**復旧した**。画面に出た出力:

```
! token.json が使えません: invalid_grant: Token has been expired or revoked.
  リフレッシュトークンが失効しているので、同意画面をやり直します。
Please visit this URL to authorize this application: https://accounts.google.com/o/oauth2/auth?...client_id=639758631694-...
✓ 認証情報を保存しました: token.json（コミットしないこと）
✓ 認証しました: 日本の最新ニュースまるわかり（UCYHTfHJOoETzvpx-VZlUTng）
```

- 修正が効いて**同意画面まで到達した**（`token.json` を消さずに復旧できた）。
- 再認証したのは**同じ2つ目のクライアント** `639758631694-…`＝クォータ分離は維持されている。
- その後もう一度 `--auth-only` を叩き、**同意画面なしで**
  `✓ 認証しました: 日本の最新ニュースまるわかり（UCYHTfHJOoETzvpx-VZlUTng）`
  を確認した（＝リフレッシュが効いている）。
- known-issues 11番に従い、`token.json` / `client_secret.json` を
  `research-and-video-ede9c9` worktree にもコピーし、そちらでも `--auth-only` の
  成功を確認した。**`video-content-research-60a976` worktree は古いクライアント
  （`393077911026-…`）のまま**にしてある（生きているので触っていない）。

## 触ってはいけないところ

- 採用ゲート（`evidence.collect()`）を緩めない。
- `state/*.json` を手で編集しない。**例外は `2D_cpARVcw0`**
  （YouTube 上に存在しない＝known-issues 8番の該当エントリ）。消すなら枠が空く。
- **生きている方のトークンをリポジトリ直下へコピーするかは未決。**
  即復旧するがクォータを分けた意味が無くなる（known-issues 14番の選択肢2）。
  勝手にやらないこと。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする（13番）。
- `.github/workflows/watchdog.yml` の監視を止めない。
