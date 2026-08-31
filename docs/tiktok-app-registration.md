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

## まだ埋まっていない5項目

| 項目 | 要件 | 誰が用意するか |
|---|---|---|
| App icon | 1024x1024px、5MB以下、JPEG/JPG/PNG。**公開表示される** | 未定 |
| Terms of Service URL | 公開されている利用規約ページ | **本人**（作る必要がある） |
| Privacy Policy URL | 公開されているプライバシーポリシーページ | **本人**（作る必要がある） |
| Web/Desktop URL | このアプリ／サービスの公式サイト | **本人**（決める必要がある） |
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
