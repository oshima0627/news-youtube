/**
 * TikTok の審査に必要な3ページを配信するだけの Worker。
 *
 *   /          サービス説明（アプリ登録の Web/Desktop URL）
 *   /terms     利用規約（Terms of Service URL）
 *   /privacy   プライバシーポリシー（Privacy Policy URL）
 *
 * 書いてあることは実装と一致していなければならない。トークンの置き場所や
 * 使うスコープを変えたら、このファイルも同時に直すこと。審査は「書いてある
 * 挙動」と「実際の挙動」の食い違いを見る。
 */

const UPDATED = "2026-08-31";

// ここだけ日本語も併記する。審査担当は英語で読むが、運営者本人と
// 日本の視聴者が読む可能性もある。
const STYLE = `
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans",
                 "Noto Sans JP", Meiryo, sans-serif;
    line-height: 1.75; color: #10182b; background: #fff;
  }
  @media (prefers-color-scheme: dark) {
    body { color: #e7ecf5; background: #10182b; }
    a { color: #ff961a; }
    header { border-bottom-color: #2a3550 !important; }
    nav a { color: #b9c3d6 !important; }
    code { background: #1b2440 !important; }
  }
  .wrap { max-width: 44rem; margin: 0 auto; padding: 2rem 1.25rem 5rem; }
  header { border-bottom: 4px solid #ff961a; padding-bottom: 1rem; margin-bottom: 2rem; }
  h1 { font-size: 1.6rem; margin: 0 0 .35rem; }
  h2 { font-size: 1.15rem; margin: 2.25rem 0 .5rem; }
  nav { font-size: .9rem; }
  nav a { color: #4a5570; margin-right: 1rem; }
  .updated { font-size: .85rem; opacity: .7; }
  code { background: #f1f3f8; padding: .1em .35em; border-radius: .25em;
         font-size: .9em; word-break: break-all; }
  ul { padding-left: 1.25rem; }
  li { margin: .35rem 0; }
`;

function page(title, body) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} — 国会ニュースまるわかり</title>
<style>${STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>国会ニュースまるわかり</h1>
  <nav>
    <a href="/">Overview</a>
    <a href="/terms">Terms of Service</a>
    <a href="/privacy">Privacy Policy</a>
  </nav>
</header>
${body}
<p class="updated">Last updated: ${UPDATED}</p>
</div>
</body>
</html>`;
}

const INDEX = page("Overview", `
<h2>What this is</h2>
<p>
  <strong>国会ニュースまるわかり (Kokkai News Marukawari)</strong> is a personal
  desktop program. Its operator runs it on their own computer to build short
  vertical news videos and post them to <em>their own</em> TikTok and YouTube
  accounts. It is not a service offered to anyone else, and it has no user
  accounts, no server, and no sign-up.
</p>

<h2>How a video is made</h2>
<ul>
  <li>A topic is chosen, and the program retrieves the <strong>verbatim passage</strong>
      from the official proceedings of the National Diet of Japan
      (<a href="https://kokkai.ndl.go.jp/">kokkai.ndl.go.jp</a>).
      If no primary source can be retrieved, no video is made.</li>
  <li>The operator writes the narration using <strong>only the facts contained in
      that passage</strong>. The on-screen quotation card must be a literal
      substring of the retrieved passage; the program refuses to render otherwise.</li>
  <li>Speech is synthesised locally, and a 1080×1920 video is rendered locally
      with ffmpeg. The TikTok version runs 70–80 seconds.</li>
  <li>The finished file is posted through the TikTok Content Posting API to the
      operator's own account. The caption carries the citation of the primary source.</li>
</ul>

<h2>Sources and licensing</h2>
<ul>
  <li>Text: proceedings of the National Diet of Japan, quoted with the session,
      date and speaker shown on screen and in the caption.</li>
  <li>Images: the Prime Minister's Office of Japan, Japanese government ministries,
      and Wikimedia Commons, used under their respective licences, with attribution
      shown in the video description. Press agency photographs are never used.</li>
</ul>

<h2>Use of the TikTok API</h2>
<p>
  The program uses <code>user.info.basic</code> to read the operator's
  <code>open_id</code> — solely to confirm, before uploading, that a video is going
  to the intended account — and <code>video.publish</code> to post the finished
  video. It reads no other data from TikTok.
</p>
`);

const TERMS = page("Terms of Service", `
<h2>Terms of Service</h2>

<h2>1. Scope</h2>
<p>
  These terms apply to the software described on this site and to the pages on this
  site. The software is operated by its author for the author's own accounts. It is
  not licensed, sold, or made available to third parties, and there is no user
  registration.
</p>

<h2>2. No warranty</h2>
<p>
  This site and the software are provided "as is", without warranty of any kind,
  express or implied. The author is not liable for any damages arising from their
  use.
</p>

<h2>3. Content</h2>
<p>
  Each published video quotes a passage from the official proceedings of the
  National Diet of Japan and displays the session, date and speaker on screen. The
  narration is written by a human using only the facts in that passage. Quotations
  from public records are used for the purpose of reporting and commentary.
</p>
<p>
  If you believe a video misrepresents a source, please get in touch using the
  contact details below and it will be corrected or removed.
</p>

<h2>4. Third-party platforms</h2>
<p>
  Videos are published on TikTok and YouTube. Your use of those platforms is
  governed by their own terms, not by these.
</p>

<h2>5. Changes</h2>
<p>
  These terms may be updated. The date at the foot of this page shows when it was
  last changed.
</p>

<h2>6. Contact</h2>
<p>You can reach the operator at <a href="mailto:info@nexeed-lab.com">info@nexeed-lab.com</a>.</p>
`);

const PRIVACY = page("Privacy Policy", `
<h2>Privacy Policy</h2>

<h2>1. Summary</h2>
<p>
  This program has one user: its operator. It collects no personal data from anyone
  else, runs no server, uses no analytics, sets no cookies, and shares nothing with
  third parties.
</p>

<h2>2. This website</h2>
<p>
  These pages are static. They set no cookies, embed no trackers, and record no
  analytics about visitors.
</p>

<h2>3. Data obtained from TikTok</h2>
<p>
  When the operator authorises the program, TikTok issues an access token, a refresh
  token, and the operator's <code>open_id</code>.
</p>
<ul>
  <li>These values are written to a file on the operator's own computer
      (<code>tiktok_token.json</code>) and are stored nowhere else. There is no
      server and no database.</li>
  <li>They are transmitted only to TikTok's own API endpoints, over HTTPS, in order
      to post videos.</li>
  <li><code>open_id</code> is used solely to check, before an upload, that a video is
      going to the intended account.</li>
  <li>No other TikTok data is requested, read, or stored. No data belonging to any
      other TikTok user is accessed.</li>
</ul>

<h2>4. Scopes requested</h2>
<ul>
  <li><code>user.info.basic</code> — read the operator's <code>open_id</code> to
      verify the destination account.</li>
  <li><code>video.publish</code> — post a finished video to the operator's own
      profile.</li>
</ul>

<h2>5. Retention and deletion</h2>
<p>
  Tokens are kept locally until they expire or are revoked. Deleting the local file
  removes them immediately. The operator can revoke the program's access at any time
  from TikTok's own security settings, which invalidates the tokens.
</p>

<h2>6. What is published</h2>
<p>
  The videos themselves contain quotations from the public proceedings of the
  National Diet of Japan, including the names of the members of the Diet who spoke,
  and photographs published by Japanese government bodies or hosted on Wikimedia
  Commons under their respective licences. All of this material is already public.
</p>

<h2>7. Children</h2>
<p>
  The program is not directed at children and collects no data from them.
</p>

<h2>8. Changes</h2>
<p>
  This policy may be updated. The date at the foot of this page shows when it was
  last changed.
</p>

<h2>9. Contact</h2>
<p>You can reach the operator at <a href="mailto:info@nexeed-lab.com">info@nexeed-lab.com</a>.</p>
`);

const ROUTES = {
  "/": INDEX,
  "/terms": TERMS,
  "/terms/": TERMS,
  "/privacy": PRIVACY,
  "/privacy/": PRIVACY,
};

export default {
  fetch(request) {
    const { pathname } = new URL(request.url);
    const html = ROUTES[pathname];
    if (!html) {
      return new Response("Not found", {
        status: 404,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }
    return new Response(html, {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "public, max-age=300",
      },
    });
  },
};
