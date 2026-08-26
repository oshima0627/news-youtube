# HANDOFF

最終更新: 2026-08-26（セッション: ショート→長尺の関連動画リンク）

## いま何をしているのか

**ショート全38本の「関連動画」欄に長尺1本目（`UqjB--sNTKk`）を紐づけた。**
コードは変えていない。YouTube Studio の UI 操作のみ。

背景: 長尺 `UqjB--sNTKk` は 8/20 公開で 6日間 0再生。ショートからの導線が
1本も無かったため、回遊を作って測れる状態にした。

## 今回やったこと

### 1. 「紐づいているか」を実測で確認した（結論: 紐づいていなかった）

- YouTube Data API で公開中の説明文を引き直し → **ショート・長尺とも
  他動画へのリンクは0件**。
- `playlists.list` → **再生リスト0本**。
- ソース全体を `playlist|endscreen|youtu\.be|関連|related` で検索 → **ヒット0**。
  説明文を組み立てているのは [`run_daily.py:275`](scripts/run_daily.py:275) と
  [`run_long.py:220`](scripts/run_long.py:220) の2箇所だけで、どちらも他動画を参照しない。

### 2. API に「関連動画」フィールドが無いことを確認した

YouTube Data API v3 の discovery document を取得して `Video` リソースの
プロパティを列挙 → **関連動画に相当するフィールドは存在しない**。
`related` の出現箇所は `relatedPlaylists`（チャンネル）・`RelatedEntity`（通報）等で無関係。

→ **Studio の UI からしか設定できない。** 自動化する手段は現状ない。

### 3. Studio UI で全38本に設定した

Chrome拡張（claude-in-chrome）で `studio.youtube.com/video/<id>/edit` を1本ずつ開き、
右カラム「関連動画」→「特定の動画の選択」→ 長尺を選択 →「保存」。

**設定した38本**（`state/published.json` の全40件から、長尺 `UqjB--sNTKk` と
Studio で手動削除済みの `2D_cpARVcw0` を除いた全数）:

```
4pOyrwI3lJo n6T9cs5LEJQ OvFoE-YgMqY yKVCHhBMGkE Qe7ZMj1U-kc 8ebRhoO41tM
aSokL2axk3U pVNNZZ4VKSA z_jxJz-zIW0 RsfdxzLDdPE C5_poVw8hlM veU-6dJhtR0
zC8OJmUT9Us WRe7-4HJ2gA bhXSBA5dqMw P8bhgdLNmjY G_eRUPj6WlQ TWxWGgXFYAw
U8t5KlxP9xo XuHs_x6lHSI Ql_ylXmaqBM MjkjrJVCN0w R_dirwcTjqs aK8tBgckL9k
yFMt61Dp6Is RMyRIInAXRw CXdd3ODNGqk XW392Sr9Zew d0Ao4COVCQ4 1j8f3nA-Xbo
nkmR2E-BZIs ucgAxCULa7Q fW8ji4CAq9k EBnFdZpSwsc NFjiJ0U54ZI xNkyuxioRJk
hMJkj8UMZjg -4cbnhI5wVA
```

## 検証済みの事実（実際に画面に出した出力）

- **38本すべてで「変更を保存しました」を画面で確認した。**
  1本ずつスクリーンショットで、保存後に「関連動画: 国会質疑を解説｜議長就任に一千万円…」
  と表示され `保存` ボタンが無効化されていることを見ている。
- **視聴者側に出ることを確認した。** `youtube.com/shorts/4pOyrwI3lJo` を開くと
  タイトル直下に `▶ 国会質疑を解説｜議長就任に一千万円・日本はICC最大の拠出国・熊本地震十年`
  のリンクが出る。
- **説明文が壊れていないことを API で全件確認した**（下記の事故があったため）:

  ```
  説明文に混入なし: 38 件
  混入あり: なし
  ```

### 途中で起きた事故と復旧（2件、どちらも保存前に戻した）

Studio のダイアログは開くのが遅く、**同一 browser_batch 内で「鉛筆クリック →
検索欄に入力」を続けると、ダイアログが開く前の入力が説明文に入る**。
`zC8OJmUT9Us` と `bhXSBA5dqMw` で説明文末尾に `国会質疑を解説` が混入した。
どちらも**保存前に気づき `変更を元に戻す` で復旧**、その後あらためて設定した。
上の API 全件チェックはこの復旧が効いていることの裏づけ。

## 未検証のもの

- **回遊が起きるか（長尺の再生数が伸びるか）は未測定。** リンクを置いただけ。
- パイプライン産以外の**古い動画（チャンネル全196本のうち約156本）は未設定**。
  今回触ったのは `published.json` にある38本だけ。
- 今後アップロードするショートには**自動では付かない**（API に無いため）。
  作るたびに Studio で手作業になる。
- 予約8本の「見出しと引用が噛み合っているか」の**人手**確認（前セッションからの持ち越し）。
- 認証の再失効（前セッションからの持ち越し。下記）。

## 次にやること

1. **数日後に長尺 `UqjB--sNTKk` の再生数を見る。** 0のままなら導線の問題ではなく
   題材かサムネイルなので、そこを測ってから本数を増やす判断をする。

   ```bash
   python scripts/watch_channel.py --within 14
   ```

2. **2026-09-02 前後に認証の生死を見る**（前セッションからの持ち越し。
   `token.json` が 8/19 発行の2つ目クライアントで、8/26 に `invalid_grant` で
   一度死んだ。再認証済みだが原因未特定。詳細は `docs/known-issues.md` 14番）。

   ```bash
   python scripts/upload_youtube.py --auth-only
   ```

3. 公開時刻前に、予約8本の見出しと引用の噛み合いを**人が**見る。
4. 認証が生きていれば 8/30 18:30 以降の枠を埋める。

   ```bash
   python scripts/run_daily.py --limit 1 --days-ahead 4
   ```

5. **新しく作るショートにも関連動画を付けるなら、公開前に Studio で手作業**。
   忘れると付かない。付け忘れを機械的に検出する手段は無い（API で読めないため）。

## 触ってはいけないところ

- 採用ゲート（`evidence.collect()`）を緩めない。
- `state/*.json` を手で編集しない。例外は `2D_cpARVcw0`（YouTube 上に存在しない）。
- **Studio を自動操作するときは、ダイアログが開いたことをスクリーンショットで
  確認してから入力する。** 同一バッチで続けると説明文が壊れる（上記の事故）。
  保存前なら `変更を元に戻す` で戻せる。
- 「関連動画」は API から読めない。**設定済みかどうかを機械的に確認できない**ので、
  設定したら都度その場で画面を見て確かめる。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする（known-issues 13番）。
- `.github/workflows/watchdog.yml` の監視を止めない。
