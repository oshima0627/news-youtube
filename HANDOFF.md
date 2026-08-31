# HANDOFF

最終更新: 2026-08-31（セッション: TikTok 投稿の実装 → アプリ登録 → Sandbox 構築 →
実 API での認証に成功 → **TikTok への初投稿に成功（SELF_ONLY）。投稿経路は全部検証済み**。
**TikTok は審査へ提出済み（in review）。YouTube は 9/2 07:30 の枠の動画を
ビルドし、アップロードの確認待ち**）

## いま何をしているのか

**TikTok にも投稿できるようにしている。** ショートと同じ一次資料・同じ引用から、
本文だけを長く書いた **70〜80秒版**を `work/<id>/tiktok/` に作り、YouTube の枠と
同じ時刻に Direct Post API で投稿する。

**コードは完成していて全経路を通した。Sandbox も実 API を叩ける状態まで設定した。**
Production 側の未入力は**デモ動画だけ**。ただしポータルは全項目が埋まるまで下書き
保存できないので、**Production の入力はまだブラウザのタブ上にしかない**
（下記「いま詰まっているところ」）。

**投稿経路はすべて実 API で検証済み。審査にも提出した（in review）。**
**こちらから進められることは無く、TikTok の審査結果を待つ段階。**
承認が下りるまで公開投稿はできない（審査前はアカウントを非公開にしたうえで
SELF_ONLY のみ）。承認されたら `tiktok_client.json` を Production の鍵に
差し替えて運用を始める。

YouTube の運用は変わっていない: **枠は 2026-09-01 18:30 JST まで埋まっている
（予約11本）。次の空きは 9/2 07:30。** `ANTHROPIC_API_KEY` は無いので、台本は
対話セッションが書いて `--script` で渡す。

## 今回やったこと

### 1. TikTok 投稿の一式を実装した（TDD、新規109テスト）

| ファイル | 役割 |
|---|---|
| `scripts/tiktok.py` | **投稿を止める判断だけ**を集めた。3つの関門と純関数 |
| `scripts/tiktok_api.py` | HTTP クライアント。OAuth(PKCE)・init・アップロード・完了確認 |
| `scripts/upload_tiktok.py` | 投稿CLI。`post()` に全経路が入る |
| `scripts/post_tiktok_due.py` | 定時タスクの入口。枠が来たものを投げる |
| `scripts/tiktok_queue.py` | `state/tiktok_queue.json` / `tiktok_posted.json` |

既存への変更（**既定の引数は現在の挙動そのままで、既存の呼び出しは変わらない**）:

- `scripts/build_short.py`: `resolve_sources()` を切り出し、`build()` に
  `assets_dir` / `recipe_id` / `target_min` / `target_max` を追加
- `scripts/script_writer.py`: `TIKTOK_MIN_CHARS=410` / `TIKTOK_MAX_CHARS=450` と
  `load_tiktok_script()`（`load_script` を呼ぶので source_url の検証は共通）
- `scripts/run_daily.py`: `--tiktok-script`、`parse_args()` の切り出し、
  `write_tiktok_meta()` / `build_tiktok_variant()` / `try_build_tiktok_variant()`
- `CLAUDE.md`、`.gitignore`（`tiktok_client.json` / `tiktok_token.json`）
- 仕様書: `docs/superpowers/specs/2026-08-30-tiktok-posting-design.md`

### 2. 動画を1本作って、投稿経路を最後まで通した（`--dry-run`）

```bash
python scripts/run_daily.py --keyword "医師偏在指標 新潟" \
  --script <短尺台本.json> --tiktok-script <TikTok台本.json> \
  --dry-run --days-ahead 3 --limit 1
```

### 3. TikTok 開発者アプリを作り、デモ動画以外を全部入れた

本人が開発者アカウントを作成してログインしたあと、ブラウザ操作で進めた。
**入力した値は全部 [`docs/tiktok-app-registration.md`](docs/tiktok-app-registration.md) に控えてある。**

### 4. Sandbox（`local-desktop`）を作って設定した

ID `7679915999907088404`。**未承認アプリは Sandbox で実演したデモ動画でないと
審査に出せない**うえ、実 API を審査前に叩けるので HTTP 部分の検証にも使う。
設定内容は [`docs/tiktok-app-registration.md`](docs/tiktok-app-registration.md)。

### 5. 手で置く認証情報ファイルを BOM 付きでも読めるようにした

`tiktok_client.json` は人がエディタで作る。Windows のエディタは UTF-8 に BOM を
付けて保存することがあり、`json.loads` はそれで落ちる。出るのは「JSONとして
読めません」だけで原因に辿り着けないので、`utf-8-sig` で読むようにした。

### 6. Sandbox の鍵で実 API に到達した（**この工程で最大の成果**）

`upload_tiktok.py --auth-only` が通り、OAuth（PKCE の hex SHA256 を含む）・
トークン保存・`creator_info/query` が**本物のサーバで動くことを確認**した。
ここは実装以来ずっと未実行だった部分。

### 7. Sandbox の鍵で「審査が下りた」と読ませないようにした

最初の実行で `--auth-only` は「✓ 審査が下りています」と表示した。**誤り。**
Sandbox の `creator_info` は審査に関係なく `PUBLIC_TO_EVERYONE` を返すのに対し、
Production はまだ Draft で申請すらしていない。このまま進むと「通ったつもり」で
本番運用に入る。`client_key` の接頭辞（実測: Sandbox は `sbaw...`）で見分けて
警告する。**接頭辞は1件しか実測していないので警告にだけ使い、投稿の可否には
使わない**（`tiktok.py` の関門だけが投稿を止める）。

### 8. 投稿を2回試し、403 の本当の原因を突き止めた（**この工程で最も重要**）

1回目（公開＝`PUBLIC_TO_EVERYONE`）も2回目（`--allow-self-only`）も、
`video/init/` が **同じ HTTP 403** で拒否した:

```
{"error":{"code":"unaudited_client_can_only_post_to_private_accounts", ...}}
```

**SELF_ONLY でも同じだったことから、原因は投稿の公開範囲ではないと判った。**
エラーが参照するガイドラインにこうある:

> All user accounts using the API client to post must be set to private
> at the time of posting.

つまり **「private accounts」は投稿の公開範囲ではなく TikTok アカウントの設定**。
審査が下りるまでの制約は3つ:

- **アカウントを非公開に設定していること**
- 24時間で5ユーザーまで
- 内容は SELF_ONLY のみ

否定された当初の前提:

| | 仕様書に書いていた想定 | 実測 |
|---|---|---|
| 未審査での投稿 | API は成功を返し、中身が SELF_ONLY に強制される | **403 で拒否される** |
| `privacy_level_options` | 審査が下りたかが判る | **判らない**（未審査でも3つ返った） |

当初恐れていた事故（誰にも届かない動画が成功ログ付きで積み上がる）は
TikTok 側が拒否するので**そもそも起きない**。`scripts/tiktok.py` の
docstring・`CLAUDE.md`・仕様書を実測に合わせて訂正した。関門自体は残す
（選べない値を送って後段で落ちるより手前で止まるほうが安い）。

### 9. TikTok への初投稿に成功した（**未検証部分がゼロになった**）

本人の明示的な承諾を得て、TikTok アカウントを一時的に非公開に切り替えてから投稿。
**終わり次第すぐ公開へ戻した**（非公開／コメント設定とも元の状態を確認済み）。

```
✓ 投稿しました: publish_id=v_pub_file~v2-1.7680043967891195924 (SELF_ONLY, 74.17秒)
```

これで `video/init/` → 動画の PUT 送信 → `status/fetch` の
`PUBLISH_COMPLETE` までが実サーバで通った。

### 10. workdir のキーを正規化した（初投稿の記録から見つかった欠陥）

記録が `work` + バックスラッシュ + `1d04e9d8cd04` + ... で入っていた。Windows で
Path を `str()` するとこうなる。CLI に `work/a/tiktok` と打っても記録は
バックスラッシュで入るので、素の文字列比較だと**同じ場所を別物として扱い、
重複防止が効かず同じ動画が2本 TikTok に並ぶ**。区切り文字をスラッシュに寄せ、
**読むときにも正規化する**（書くときだけ揃えると正規化前の記録が引けなくなって
同じ事故が起きる）。既存の記録が引けることを実データで確認した。

### 11. 重複投稿の関門を post() の中へ移した（**CLAUDE.md が名指しする穴と同型**）

重複防止をキューのフィルタ（`tiktok_queue.due_entries`）にだけ置いていたため、
**`upload_tiktok.py` を直接叩く経路が素通りし、同じ動画を何度でも投稿できた**。
`post()` は `load_posted` を一度も見ていなかった。

CLAUDE.md の「関門は1つにして、全経路がそれを通る形にする／`run_daily` にだけ
検証を置いた結果、手動CLI経路が素通りした」とまったく同じ形。全経路が通る
`post()` の中へ移し、判定は尺より前に置いた（通信もアップロードもしないうちに
止まる）。`tiktok.AlreadyPosted` / 終了コード8。

### 12. デモ用の動画を1本作った（`work/13ed80ac2dc1/`）

`work/1d04e9d8cd04/tiktok` は投稿済みで関門が再投稿を止めるため、別題材で作成。
題材は「介護職員の賃金は全産業平均より八万円低い」（参議院厚生労働委員会
2026-06-16 永井幸子）。数字が3つ入り、家計に直結し、事実の指摘なので
政治的に中立 — TikTok の審査担当も見ることを考えて選んだ。

```bash
python scripts/run_daily.py --keyword "介護職員 賃金 全産業平均"   --script <短尺台本.json> --tiktok-script <TikTok台本.json>   --dry-run --days-ahead 3 --limit 1
```

### 13. デモ用の回を投稿し、ターミナル側の録画が完成した

本人がアカウントを非公開にして録画しながら実行。2本目の投稿も成功した:

```
work/13ed80ac2dc1/tiktok
  publish_id=v_pub_file~v2-1.7680058761830205460
  status: PUBLISH_COMPLETE  (SELF_ONLY, 74.19秒)
```

録画: `C:/Users/oshim/Videos/Captures/Windows PowerShell 2026-08-31 14-13-19.mp4`
（mp4 / h264 / 1920x1032 / 74.5秒 / 40.1MB。**条件内**）。
フレームを抜き出して中身を確認済み。`--auth-only` の出力（Login Kit /
user.info.basic、`使っている鍵: Sandbox`）と投稿の出力（Content Posting API /
video.publish）が映っている。

**ただしターミナルだけで、TikTok 側の画面が映っていない。** 審査は連携の
端から端までを求めるので、プロフィールに投稿が並ぶところと再生を映した
2本目が要る（デモ動画は5本までアップロードできる）。

### 14. 申請フォームを完成させて保存した

Claude が Production のタブを誤って上書きし、入力が消えた。**`Import` →
`Import from Sandbox` → `local-desktop` で一括復旧できた**（Sandbox は
Apply changes 済みで保存されていたため）。Sandbox に無い項目
（App review の説明文・デモ動画）だけを追加した。

デモ動画は Claude のアップロード上限（1回10MB）を超えていたので再エンコードした:

```
demo1_terminal.mp4: 40.1 MB → 0.3 MB   （ターミナル、74.5秒）
demo2_tiktok.mp4:   28.1 MB → 0.6 MB   （TikTok の画面、27.7秒）
```

`-crf 30 -r 10`、解像度は据え置き。**圧縮後のフレームを目視して、
ターミナルの日本語もキャプションの小さな文字も読めることを確認した。**

**Save が通った＝全必須項目が埋まっている**（このポータルは1つでも欠けると
保存を拒否する）。再読み込み後も保持を確認。

### 15. 審査に提出した（2026-08-31）

本人の明示的な承諾を得て `Submit for review` を押した。申請理由:
`First submission: requesting video.publish for a personal desktop tool that
posts the creator's own news videos.`（112/120）

```
This version of 日本の最新ニュースまるわかり is in review.
There may be a delay in the app review process due to a high volume of requests.
```

ボタンは `Recall`（取り下げ）に変わっている。

### 16. YouTube の宿題2件に答えが出た（API で引き直し）

```
8zGOoD1GhUQ  public  再生=1201  高評価=13  ビザ手数料3000円→1万5000円
myjKRuLTmXw  public  再生=1062  高評価=6   教員不足3827人・採用倍率2.9倍
hQm4LqOv18o  private publishAt=2026-08-31T09:30:00Z（本日18:30。正常）
```

- **`--script` 経路の初公開が成功した**（`8zGOoD1GhUQ`、1201再生）。
- **`myjKRuLTmXw` に配信制限の兆候は無い。** 1062再生は通常の帯
  （1,062〜2,383）の中で、`R_dirwcTjqs` の26再生のような落ち込みは起きていない。
  自殺者数への言及を理由に落とされた形跡は無い。**この懸念は解消。**

### 17. 維持率を測り直して題材を選んだ

`retention_report.py` の出力（パイプライン産）:

```
12436  159.4%  食料品の消費税1%で減収4.3兆円      ← 突出
 2389   54.7%  能登半島地震で最大15万軒断水
 2006   93.2%  茂木外相「ラブロフ外相と八時間交渉」
 ...
 1146   57.9%  最低賃金と「壁」
 1040   95.4%  ガソリン価格「G7で最も安い水準」
 1017   49.1%  奨学金「四人に一人が返済中」
```

**維持率が高くても再生が伸びない例が多い**（ガソリンは95.4%で1040）。
床は1,000〜1,200で、そこを抜けたのは家計に直結する金額の回だけ。
**仮説「家計に直結する金額の回が伸びる」は今のところ支持されている。**

### 18. 9/2 07:30 の枠の動画をビルドした（`work/70d2a7819750`）

題材は「年末調整で一人3万〜6万円の所得税減税」（衆議院予算委員会
2026-07-27 城内実）。12月に起きる家計の金額なので上の仮説に乗る。

```
試行1: speedScale=1.056 → 実尺58.60秒  テロップ22枚
尺: voice.wav 58.60秒 → video.mp4 58.60秒（差 +0.00秒）
```

画面外に出たテロップは0行。**アップロードは本人の確認待ち**（Claude は
YouTube を動かす操作を確認なしで行わない）。

**既知の見た目の欠陥**: 引用カードが「納税者1人当たりの**三**から**6**万円」
と表記が混ざる。`normalize_numerals` は「三か月」は直すが「三から」は直さない。
7通り試した結果、3〜6万円の幅を保ったままきれいに出る抜き出し方は無かった。
`HANDOFF.md` に記録のある同種の件（「50分の一」）と同じ扱いで、作り直さない判断。

### 19. 審査に要る3ページを Cloudflare Workers で公開した

`site/`（`wrangler.jsonc` + `src/index.js`）。`cd site && npx wrangler deploy`。
利用規約・プライバシーポリシー・サービス説明と、URL 所有確認の署名ファイルを配信する。
**ページの記述は実装と一致させてある**（保存するトークンの種類と置き場所、
要求するスコープ2つ、一次資料の扱い）。実装を変えたら `site/src/index.js` も直す。

## 検証済みの事実（実際に画面に出した出力）

- **`pytest` 556 passed**（前回 435 → 今回 +121）。警告なし。
- **同じ題材から2本ビルドできた**（`work/1d04e9d8cd04/`）:

  ```
  試行1: speedScale=0.945 → 実尺58.67秒（許容範囲内）
    尺: voice.wav 58.67秒 → video.mp4 58.67秒（差 +0.00秒）  テロップ22枚
  試行1: speedScale=0.949 → 実尺74.14秒（許容範囲内）
    尺: voice.wav 74.14秒 → video.mp4 74.17秒（差 +0.02秒）  テロップ28枚
  ```

  **TikTok版は 74.17秒。** ffprobe で実測し、`tiktok.assert_over_a_minute` を通過。
- **投稿経路を実物で最後まで通した**（送信先の API だけ差し替え。それ以外＝
  尺の測定・3つの関門・キャプション生成・完了確認・キューの記録は本番と同じコード）:

  ```
  publish_id: publish-sim-1 / privacy_level: PUBLIC_TO_EVERYONE
  duration: 74.166667 / status: PUBLISH_COMPLETE
  source_info: {"video_size": 3036922, "chunk_size": 3036922, "total_chunk_count": 1}
  キュー: 枠前(07:00)→[] / 枠後(07:30)→[work/1d04e9d8cd04/tiktok] / 投稿後→[]
  ```

- **キャプションは 153 runes**（上限2200）。画面を目視で確認（`stage.png` /
  `frames/002.png`）。被写体は小林一大本人で発言者と一致。引用カードは
  「医師偏在指標で全国第44位」で逐語引用の部分文字列。
- **テロップのはみ出しは実質なし。** 両版とも最大右端 1054px、画面幅 1080px の内側。
- **開発者アプリを作成した。** App ID `7679774568128202772`、Ownership **Individual**、
  App type **Other**（どちらも作成後は変更不可）。
- **入力できた項目**: App name / Category=News / Description(112字) /
  Platforms=Desktop / Products=Login Kit + Content Posting API /
  **Direct Post=ON** / Scopes=`user.info.basic`,`video.publish`,`video.upload` /
  Redirect URI(Desktop)=`http://localhost:8723/callback` / App review の説明文(922字) /
  App icon / 3つのURL。**エラーは 6 → 1（デモ動画のみ）まで減った。**
- **Save が拒否されることを確認した**:

  ```
  Please correct all errors before you save changes, or submit changes for review.
  ```

- **URL の所有確認が通った**: `Your property has been verified` /
  URL prefix `https://kokkai-news-maruwakari.oshima6-27.workers.dev/` / Verified。
- **3ページが公開されていることを確認した**（`/` `/terms` `/privacy` が 200、
  未定義パスは 404、署名ファイルが 68バイトで一致、連絡先 `info@nexeed-lab.com` を掲載）。
- **誤った名前の Worker を消した**: `Successfully deleted kokkai-news-marukawari`、
  旧URLは HTTP 404。TikTok 側の旧 URL prefix も `Delete success` で削除済み。
  （`marukawari` は誤り。まるわかり＝`maruwakari`）
- **Sandbox を作って設定した。再読み込み後も残っていることを確認した**:
  Target Users=`naotaka_oshima`(11:50 追加) / Products=Login Kit + Content Posting API /
  Direct Post=ON / Scopes=`user.info.basic`,`video.publish`,`video.upload` /
  Redirect URI(Desktop)=`http://localhost:8723/callback` /
  Category=News / Description / 3つのURL / App icon。
- **Client secret のページからの読み出しは安全機構に止められた**（妥当な動作。
  秘密鍵を会話の記録に残さずに済む）。**本人が手で置く方針に切り替えた。**
- **実 API での認証に成功した**（Sandbox の鍵、2026-08-31）:

  ```
  ✓ tiktok_token.json を保存しました
  ✓ 認証しました: @naotaka_oshima（open_id=-000jeuhnstVO-12Jyf4ruZN0AXnIL1v9vN0）
  - 使っている鍵: Sandbox
  - 選べる公開範囲: ['PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY']
  ```

- **`creator_info/query` の実応答**:
  `max_video_post_duration_sec=600` / `creator_username=naotaka_oshima` /
  `stitch_disabled=false` / `comment_disabled=false` / `duet_disabled=false`。
- **実データで3つの関門を通した**: 実尺74.17秒 → 尺の下限(61秒)✓ /
  アカウント上限(600秒)✓ / 公開範囲の解決 → `PUBLIC_TO_EVERYONE`✓。
- **アカウントが公開のままだと、公開でも SELF_ONLY でも 403 で拒否される**
  （3回実行、いずれも同じエラー）。
- **アカウントを非公開にしたら投稿が通った**（2026-08-31）:

  ```
  ✓ 投稿しました: publish_id=v_pub_file~v2-1.7680043967891195924 (SELF_ONLY, 74.17秒)
  ```

  `state/tiktok_posted.json` に `status: PUBLISH_COMPLETE` で記録された。
- **重複投稿の関門が実データで効くことを確認した**。同じ workdir をもう一度
  叩くと、APIを一度も呼ばずに終了コード8で止まる:

  ```
  ✗ workd04e9d8cd04	iktok は投稿済みです
    （publish_id=v_pub_file~v2-1.7680043967891195924）。
  ```
- **アカウント設定を元に戻したことを画面で確認した**: 非公開アカウント=オフ、
  コメント=誰でも（非公開にすると自動で「フォロワー」に変わるが、戻すと復帰する）。
- **投稿がプロフィールに実在することを確認した**（本人のスクリーンショット）。
  `https://www.tiktok.com/@naotaka_oshima` に1本目が鍵アイコン付きで並んでいる。
  API の `PUBLISH_COMPLETE` だけでなく、TikTok 上に動画があることの確認。
- **`privacy_level_options` はアカウントの公開設定を反映する**（2026-08-31 実測）:

  | アカウント | 返ってきた選択肢 |
  |---|---|
  | 公開 | `PUBLIC_TO_EVERYONE` / `MUTUAL_FOLLOW_FRIENDS` / `SELF_ONLY` |
  | 非公開 | `FOLLOWER_OF_CREATOR` / `MUTUAL_FOLLOW_FRIENDS` / `SELF_ONLY` |

  **どちらも審査状態とは無関係。** 公開アカウントで `PUBLIC_TO_EVERYONE` が
  返っても投稿は 403 で拒否された。
- **デモ録画を2本撮った**（本人の作業）。Xbox Game Bar は**画面全体ではなく
  フォーカス中のアプリだけ**を録るので、ターミナルとブラウザで別々に撮った。
  1本目に TikTok の画面が入っていなかったのはこれが理由。
- **申請フォームが保存できた**。エラー0件。再読み込み後も
  アイコン・3つのURL・説明文(978/1000)・Desktop・Direct Post・デモ動画2本が保持。
- **審査に提出した**。画面に `is in review` が表示され、ボタンが `Recall` に変わった。
- **デモ用の動画をビルドした**（`work/13ed80ac2dc1/`）:

  ```
  試行1: speedScale=0.975 → 実尺58.63秒  テロップ20枚   （YouTube版）
  試行1: speedScale=0.978 → 実尺74.19秒  テロップ25枚   （TikTok版）
  ```

  画面外に出たテロップは両版とも0行（最大右端 1054px / 画面幅 1080px）。
  `expected_tiktok_open_id` も入っている。画像は発言者の写真が無く
  **汎用の国会議事堂**（設計どおりのフォールバック）。stage.png を目視確認済み。
- **`meta.json` を正規の経路で作り直した**（手で編集していない）。
  `run_daily.write_tiktok_meta` を呼び、`expected_tiktok_open_id` に
  トークンから読んだ open_id が入ることを確認した。

- **`wrangler --version` = 4.127.1、`wrangler whoami` は認証済み**（アカウントの
  権限一覧が返った）。
- **TikTok API の仕様を実際のドキュメントで確認した**:
  - 未審査クライアントの投稿は全て SELF_ONLY に強制される
  - Direct Post に `schedule_time` 相当のフィールドは**無い**
  - キャプション上限 2200 UTF-16 runes、`creator_info/query` を先に呼ぶ必要あり
  - PKCE の `code_challenge` は **hex エンコードの SHA256**（base64url ではない）
  - **Desktop アプリとして登録したときだけ** redirect URI に localhost と http が使える
  - アクセストークン24時間 / リフレッシュトークン365日
  - Creator Rewards: 60秒以上・フォロワー1万人・直近30日10万再生・個人アカウント

## いま詰まっているところ

**開発者ポータルのフォームは、必須項目が全部埋まるまで下書き保存できない。**
いま入力した内容は**開いているブラウザのタブ上にしかない**（タブは開いたまま
にしてある）。閉じたら `docs/tiktok-app-registration.md` を見て再入力する。

| 項目 | 状況 |
|---|---|
| TikTok の審査 | **提出済み（in review）。** 数日〜数週間かかるのが普通 |
| 9/2 07:30 の枠 | **本人の確認待ち。** `work/70d2a7819750` をアップロードして予約するか |

TikTok の審査を待つ間も、YouTube 側は無傷で動く
（`--tiktok-script` を付けなければ従来どおり）。

**コード側の未検証はもう無い。** 残っているのは TikTok の手続きだけ。

デモ動画を撮るときは、**もう一度アカウントを非公開にする必要がある**
（審査前の投稿はその状態でしかできない）。撮り終えたら公開に戻すこと。

**Production はデモ動画が埋まるまで Save も Submit もできない。** つまり
いまタブ（`.../pending`）を閉じると App icon・3つのURL・説明文の入力が消える
（URL の所有確認だけはポータル側に保存されているので残る）。再入力は
`docs/tiktok-app-registration.md` を見れば機械的にできる。

**Sandbox 側は Apply changes 済みなので保存されている。**

## 未検証のもの

- **Production の審査は未申請（Draft）。**
  Sandbox で `PUBLIC_TO_EVERYONE` が返るのは審査とは無関係だと実測で確定した。
- **アカウントを公開に戻したあと、SELF_ONLY の投稿がどう扱われるかは未確認。**
- **2026-08-31 14:13 時点でアカウントが非公開のままの可能性がある。**
  録画後に公開へ戻したかを確認すること。
- **`run_daily.py --tiktok-script` からキューに積んで
  `post_tiktok_due.py` で投げる経路は、実 API では未実行。**
  今回は `upload_tiktok.py` を直接叩いた。
- **Content Posting API が個人アカウントで使えるかは未確認。** Business
  アカウント必須だと Creator Rewards（個人アカウント必須）と両立しない。
  ただし `@naotaka_oshima` で `creator_info` が通ったので、少なくとも
  このアカウントでは API が使える。
- **`work/1d04e9d8cd04/tiktok/meta.json` の `expected_tiktok_open_id` は空。**
  認証前に作ったため、このバリアントはこのままでは投稿できない。認証後に作り直す。
- 今回の題材（医師偏在）は YouTube にも投稿していない（`--dry-run`）。
- 定時タスク（schtasks）はまだ登録していない。

## 次にやること

1. **9/2 07:30 の枠にアップロードする**（本人の確認待ち）:

   ```bash
   python scripts/upload_youtube.py work/70d2a7819750
   python scripts/upload_youtube.py work/70d2a7819750 --schedule 2026-09-02T07:30:00+09:00
   ```

   9/2 18:30 以降の枠はまだ空。同じ手順で埋める。題材は維持率の仮説
   （家計に直結する金額）で選ぶ。未使用の候補: `所得税 減税 年末調整` の
   高市早苗の答弁、`介護 職員 賃金`（ただし「介護職の賃上げ最大月1.9万円」が
   既出なので題材が近い）。

2. **TikTok の審査結果を待つ。** 進捗は
   https://developers.tiktok.com/app/7679774568128202772/pending で見る。
   却下されたら `Review comments` に理由が出るので、それに合わせて直して再提出。

3. ~~デモ録画を撮る~~ **完了**（参考として手順を残す）。（**Claude には画面録画ができない。本人の作業**）。
   30秒ほどでよい。`https://www.tiktok.com/@naotaka_oshima` を開き、
   新しい動画が並んでいるところ → クリックして再生 → 内容と出典が見えるところ。
   撮り終えたら**非公開アカウントをオフに戻す**。

   1本目（ターミナル側）は撮影済み:
   `C:/Users/oshim/Videos/Captures/Windows PowerShell 2026-08-31 14-13-19.mp4`

3. ~~デモ動画を録る~~（1本目の手順。参考として残す）。
   手順は 2026-08-31 に実際に通したものと同じ。録画には
   **選んだ products と scopes が全部映っている**必要がある:

   - `upload_tiktok.py --auth-only` の実行（Login Kit / user.info.basic）
   - `upload_tiktok.py work/13ed80ac2dc1/tiktok --allow-self-only` の実行
     （Content Posting API / video.publish）
   - TikTok のプロフィールに投稿が並んでいるところ
   - その動画を再生して内容と出典が見えるところ

   録画の条件: mp4 か mov、50MB以下、最大5本。
   Windows なら Xbox Game Bar（`Win + Alt + R`）で撮れる。

   前後の操作:

   - 撮影前: `https://www.tiktok.com/setting` → プライバシー →
     **非公開アカウントをオン**（これをしないと 403）
   - 撮影後: **公開に戻す**。コメント設定が「誰でも」に戻ることも確認する
     （非公開にすると自動で「フォロワー」に変わる）

3. **録画ができたら審査画面にアップロードして Save → Submit for review。**
   **申請ボタンは本人の確認を取ってから押すこと。**

（完了済み）~~本人が Sandbox の認証情報を置く~~:
   `C:\Users\oshim\Documents\projects\news-youtube\tiktok_client.json` に
   `{"client_key": "...", "client_secret": "..."}`。
   取得元は https://developers.tiktok.com/app/7679774568128202772/sandbox/7679915999907088404
   の上部 Credentials（**タブが Sandbox であることを確認する。Production の鍵では
   Sandbox の投稿は通らない**）。置かれたらワークツリーへコピーして使う。

（完了済み）~~`--auth-only` を実行する~~。
   同意画面は**私の操作できないウィンドウで開くので本人にクリックしてもらう**
   （Sandbox の Target User 追加のときもそうだった）。通れば OAuth と
   `creator_info` に**初めて実到達**する。Sandbox なので
   `privacy_level_options` は `SELF_ONLY` だけになるはず。

4. **デモ動画を録る。** Developer Portal の **Sandbox** タブを使い、
   `upload_tiktok.py --auth-only` → 動画の投稿 → TikTok 上での結果、までを
   画面録画する（mp4/mov、50MB以下）。**未承認アプリは Sandbox での実演が必須。**

4. **審査が下りたら Production の鍵に差し替えて1本投稿する**:

   ```bash
   python scripts/upload_tiktok.py --auth-only     # 審査状態も表示される
   python scripts/run_daily.py --keyword "<2語以上>" \
     --script <短尺台本.json> --tiktok-script <TikTok台本.json> \
     --days-ahead <N> --limit 1
   python scripts/post_tiktok_due.py --dry-run     # キューを確認
   ```

5. **定時タスクを登録する**（枠の時刻に実際に投げる）:

   ```
   schtasks /create /tn "tiktok-0725" /sc daily /st 07:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   schtasks /create /tn "tiktok-1825" /sc daily /st 18:25 /tr "cmd /c cd /d <repo> && python scripts\post_tiktok_due.py >> tiktok.log 2>&1"
   ```

6. **9/2 以降の YouTube の枠を埋める**（空きは 9/2 07:30 から）。実測済みで未使用の
   検索語: `医師偏在指標 新潟`、`外国人 土地`。

7. **8/31 以降に `myjKRuLTmXw`（教員不足）の再生数を他の回と比べる**
   （自殺者数に触れているため配信制限の可能性。他の回は約1,200）。

## 触ってはいけないところ

- **`tiktok.TIKTOK_MIN_SECONDS`（61.0秒）を下げない。** 60秒を割った動画は
  Creator Rewards の対象外で、投稿は通るので成功ログだけが積み上がる。
- **未審査ガードを外さない。** `--allow-self-only` は経路確認専用。
- **採用ゲート（`evidence.collect()`）を緩めない。** TikTok 版も同じゲートを通る。
- **`state/*.json` を手で編集しない**（`tiktok_queue.json` / `tiktok_posted.json` を含む）。
  キーは `Path(...).as_posix()` で正規化する。
- **重複投稿の関門を `post()` から出さない。** 呼び出し側に戻すと、また手動CLIが
  素通りする（2026-08-31 に実際に開いていた）。
- **`work/<id>/tiktok/` を投稿前に消さない。** キューが `video.mp4` を参照する。
- **PKCE の `code_challenge` を base64url に変えない。** TikTok は hex の SHA256。
- **`tiktok_api.DEFAULT_REDIRECT_URI` を変えたら、TikTok アプリ側の登録も同時に
  直す。** 文字列が完全一致でないと同意画面で止まる。
- **開発者ポータルで Submit for review を押す前に本人の確認を取る。**
- **署名ファイルの中身を画面から書き写さない。** ダウンロードした実物をコピーする
  （`l` と `I` が画面で見分けられない）。URL prefix を変えると別のコードが発行される。
- **`site/src/index.js` の記述と実装を食い違わせない。** 審査はここを突き合わせる。
- **Sandbox と Production の client_key / client_secret を混ぜない。** 別物で、
  取り違えると投稿が通らない。`tiktok_client.json` をどちらの鍵にしているか意識する。
- **client_secret を会話やコミットに残さない。** 本人が手で置く。
- **`privacy_level_options` を審査状態の指標に使わない。** 未審査でも
  `PUBLIC_TO_EVERYONE` を返す。審査状態は実際に投稿してみるまで分からない
  （2026-08-31 実測）。
- **審査前に公開投稿する方法は無い。** 403 で拒否される。回避策を探さない。
- 長尺（16:9）は当面作らない。乗る面が無く、関連動画からの回遊も15日で1再生。
- チャンネルを動かす操作の前に main を取り込んで state を最新にする。
- ログを PowerShell で読むときは `Get-Content -Encoding UTF8`。
