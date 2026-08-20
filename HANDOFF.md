# HANDOFF

最終更新: 2026-08-20 16:40 JST（セッション: 引き継ぎ確認と state 統合）

## いま何をしているのか

ブランチ分岐で起きた **8/22〜8/24 の5枠二重予約**（known-issues 13番）の後始末。
state の統合と記録は済み、**YouTube 側の解消（後着5本の移動）が人の判断待ち**。

## 今回やったこと

- README にあった旧引き継ぎ「MjkjrJVCN0w が予約待ち」を確認 →
  **実際には 8/19 から公開済みだった**（下記「検証済みの事実」）。予約は不要。
  README の該当段落を削除した。
- `claude/separate-api-quota`（8/19 に 08/22〜08/24 の6枠を予約した系列、
  HANDOFF ルール追加を含む）を main 系列にマージし、競合した
  `state/published.json` / `used.json` / `seen.json` を**両系列の和集合**で解決した。
- 二重予約の経緯を `docs/known-issues.md` 13番に記録した。

## 検証済みの事実（画面・実出力で確認したもの）

- `MjkjrJVCN0w`（出生数67万人）は YouTube Studio 上で
  **公開・公開日 2026/08/19・視聴 1,267・コメント 2**（Studio を実際に開いて確認）。
  誰が公開したかは不明。state 上は private のままだったので、CLI 経由ではない。
- Studio のショート一覧に、8/22〜8/24 の各枠で**両セットが「公開予約」として
  並んでいる**（known-issues 13番の表のとおり、5枠×2本）。
- 予約済み枠は 8/24 18:30（4pOyrwI3lJo 公益通報）まで連続で埋まっている。
  8/25 07:30 以降は空き。

## 未検証のもの

- 二重予約された10本それぞれの `status.publishAt` の正確な値は API では
  引き直していない（state ファイルと Studio の日付表示から判断）。
- 二重予約10本の「見出しと引用が噛み合っているか」の人手確認
  （README の運用ルール）はこのセッションでは行っていない。

## 次にやること

1. **二重予約の解消（人の判断）**: 提案は「後着5本（8/20 12:51 予約の
   worktree セット）を 8/25 07:30〜8/27 07:30 の5枠へ移す」。
   クォータは 50×5=250 ユニット。移すならこれを順に実行:

   ```bash
   python scripts/upload_youtube.py work/c1daab3d1773 --schedule 2026-08-25T07:30:00+09:00
   python scripts/upload_youtube.py work/36fbed9483d9 --schedule 2026-08-25T18:30:00+09:00
   python scripts/upload_youtube.py work/8dd08514e4a5 --schedule 2026-08-26T07:30:00+09:00
   python scripts/upload_youtube.py work/de37ba93d61b --schedule 2026-08-26T18:30:00+09:00
   python scripts/upload_youtube.py work/3112f5c7acb9 --schedule 2026-08-27T07:30:00+09:00
   ```

   ※ work/ ディレクトリは worktree `research-and-video-ede9c9` にある。
   実行後、known-issues 12番のとおり `videos.list` で `publishAt` を確認する。
2. 公開時刻前に、予約済み動画の見出しと引用の噛み合いを人が見る（README の運用ルール）。
3. 未予約の在庫: `8ebRhoO41tM`（ベルギー外交160周年、private・予約なし）は
   空き枠埋めに使える。`zC8OJmUT9Us`（憲法審査会）は噛み合い不良で外した経緯が
   あるので使わない（known-issues 5-b番）。

## 触ってはいけないところ

- 採用ゲート（`evidence.collect()`）を緩めない。`state/*.json` を手で編集しない
  （今回の和集合マージはブランチ競合の解決で、両スクリプトが書いた記録の統合）。
- **チャンネルを動かす操作（アップロード・予約・unpublish）の前に、必ず main を
  取り込んで state が最新であることを確かめる**（known-issues 13番の再発防止）。
- `.github/workflows/watchdog.yml` の監視を止めない。
