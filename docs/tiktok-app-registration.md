# TikTok 開発者アプリの登録内容

2026-08-31 に developers.tiktok.com で作成したアプリの設定値。

**このポータルは全項目が埋まるまで下書き保存できない**
（"Please correct all errors before you save changes" で拒否される）。
入力途中でタブを閉じると全部消えるので、入れる値をここに置いておき、
残りが揃った時点で一気に入力する。

- App ID: `7679774568128202772`
- 管理画面: https://developers.tiktok.com/app/7679774568128202772/pending
- Ownership: **Individual**（作成後に変更不可）
- App type: **Other**（作成後に変更不可）

## 入力済みの値（再入力用）

| 項目 | 値 |
|---|---|
| App name | `日本の最新ニュースまるわかり` |
| Category | `News` |
| Description | `Creates short news videos from Japan's official Diet records and posts them to the creator's own TikTok account.`（112/120） |
| Platforms | **Desktop** のみ |
| Products | **Login Kit** → **Content Posting API**（この順。Content Posting API は Login Kit が前提で、先に入れないと Add が押せない） |
| Direct Post | **ON** |
| Scopes | `user.info.basic` / `video.publish` / `video.upload`（Products を入れると自動で付く） |
| Redirect URI | Desktop タブに `http://localhost:8723/callback`（`tiktok_api.DEFAULT_REDIRECT_URI` と完全一致させる） |
| App icon | `docs/tiktok_app_icon.png`（1024x1024。テロップ帯と同じ三層） |
| Web/Desktop URL | `https://kokkai-news-maruwakari.oshima6-27.workers.dev/` |
| Terms of Service URL | `https://kokkai-news-maruwakari.oshima6-27.workers.dev/terms` |
| Privacy Policy URL | `https://kokkai-news-maruwakari.oshima6-27.workers.dev/privacy` |
| URL properties | URL prefix `https://kokkai-news-maruwakari.oshima6-27.workers.dev/` を **Verified** |

### App review の説明文（922/1000）

```
This is a desktop program the creator runs on their own PC. It posts the
creator's own short news videos to the creator's own TikTok account. There are
no other users.

Login Kit / user.info.basic: The creator authorizes the app once through the
desktop redirect URI (http://localhost:8723/callback). We read open_id only,
and compare it with the account recorded for that video before uploading, so a
video can never go to the wrong account.

Content Posting API / video.publish: The program renders a 70-80 second
vertical MP4 locally, calls creator_info/query, then posts the file with
FILE_UPLOAD and privacy_level PUBLIC_TO_EVERYONE, and polls
post/publish/status/fetch until PUBLISH_COMPLETE. Every video quotes Japan's
official National Diet proceedings as its primary source, and the caption
carries that citation.

video.upload is bundled with the product but is not used; posting always goes
through Direct Post.
```

## Sandbox（`local-desktop`）

2026-08-31 作成。ID `7679915999907088404`。
https://developers.tiktok.com/app/7679774568128202772/sandbox/7679915999907088404

**未承認のアプリはここで実演したデモ動画でないと審査に出せない。** 実 API を
審査前に叩けるので、HTTP 部分の検証にも使う。**Production とは別の
client_key / client_secret を持つ**ので、切り替えるときは
`tiktok_client.json` を差し替える。

設定済み（再読み込み後も残っていることを確認）:

| 項目 | 値 |
|---|---|
| Target Users | `naotaka_oshima`（2026-08-31 11:50 追加） |
| Products | Login Kit + Content Posting API |
| Direct Post | ON |
| Scopes | `user.info.basic` / `video.publish` / `video.upload` |
| Redirect URI | Desktop タブに `http://localhost:8723/callback` |
| Category / Description / 3つのURL / App icon | Production と同じ |

- **Platforms の Desktop にチェックを入れるまで Redirect URI の入力欄が出ない。**
  「Turn on Configure for Desktop to add your Desktop Redirect URI」と出ていたら、
  上の Platforms を先に見る。
- **Sandbox も必須項目が全部埋まるまで Apply changes できない**（Production と同じ）。
- Target User の追加は「最大1時間反映にかかる」と表示される。

## 3ページの配信（Cloudflare Workers）

`site/` に置いてある。`cd site && npx wrangler deploy` で更新できる。

| パス | 用途 |
|---|---|
| `/` | サービス説明（Web/Desktop URL） |
| `/terms` | 利用規約 |
| `/privacy` | プライバシーポリシー |
| `/tiktok<code>.txt` | URL prefix 所有確認の署名ファイル |

**ページの記述は実装と一致していなければならない。** 保存するトークンの種類と
置き場所、要求するスコープ2つ、一次資料の扱いを書いてある。審査は
「書いてある挙動」と「実際の挙動」の食い違いを見る。実装を変えたら
`site/src/index.js` も同時に直す。

連絡先は `info@nexeed-lab.com`。

### 署名ファイルは画面から書き写さない

**必ずダウンロードして中身をコピーする。** 実際に配られた1つ目の名前は
`tiktoka8lrKl0...` で、**小文字のL（l）が大文字のI（I）と画面上で見分けられない**。
書き写していたら検証に落ちていた。

**URL prefix を変えると署名ファイルも変わる。** ドメイン名を
`marukawari`（誤）→`maruwakari`（正）に直したとき、TikTok は別のコードを発行した。

**デプロイ直後は旧内容が返ることがある**（エッジのキャッシュ）。`Verify` を
押す前に `curl` で中身を確かめる。

## まだ埋まっていない1項目

| 項目 | 要件 | 誰が用意するか |
|---|---|---|
| デモ動画 | mp4/mov、50MB以下。TikTok連携の**端から端まで**を映す | **本人**（画面録画が要る） |

### デモ動画の条件（審査で最も落ちやすい）

- **未承認のアプリは、Developer Portal の Sandbox 環境を使って実演すること**が必須
- 選んだ products と scopes が**全部**映っていること。使わない scope は
  外しておかないと審査が遅れる（`video.upload` は Content Posting API に
  バンドルされていて外せないため、説明文で「使っていない」と明記してある）
- UI と操作が見えること

## 踏んだ落とし穴

- **アプリは Desktop で登録する。** Web だと redirect URI に https しか許されず
  `http://localhost:8723/callback` が拒否される
- **Content Posting API は Login Kit が前提。** 先に Login Kit を Add しないと
  Content Posting API の Add ボタンが押せない
- **Direct Post は既定 OFF。** ONにしないと `video.publish` が付かず、
  下書き（`video.upload`）投稿しかできない
- **Redirect URI の「+ Add a URI」は2つ目の枠を足すボタン。** 1つ目は
  入力欄に打つだけでよい
- 開発者ポータルは TikTok 本体とは**別アカウント**（メール＋パスワード）
- **`workers.dev` は DNS を触れない**ので、所有確認は Domain（DNSレコード）ではなく
  **URL prefix（署名ファイル）**を選ぶ
