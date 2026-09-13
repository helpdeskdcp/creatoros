# Google OAuth Verification (moving off Testing status)

CreatorOS's Google Cloud OAuth consent screen starts in **Testing** status
(Google's default for every new client). In Testing, only Google accounts
manually added as **Test users** in the Cloud Console can complete
"Connect with Google" — anyone else is blocked by Google itself before ever
reaching CreatorOS. To let any creator connect their own channel, the app
must pass Google's verification and move to **Production**.

Scopes requested (`backend/app/modules/channels/providers/youtube_data_api.py:SCOPES`)
are all **sensitive**, not **restricted** — verification needs a privacy
policy, scope justification, and a demo video, but not a third-party CASA
security assessment.

## Checklist

1. **Privacy Policy / Terms URLs** — done. Live at
   `https://creatoros.bramha.cloud/privacy` and `/terms`
   (`frontend/src/app/privacy/page.tsx`, `frontend/src/app/terms/page.tsx`).
   Paste both URLs into Cloud Console → OAuth consent screen → Edit app.
2. **App homepage** — the login page (`/login`) names and describes the app
   and links to both policy pages; this is usually sufficient. If a reviewer
   pushes back asking for a dedicated marketing homepage, build one at `/`
   before the `/dashboard` redirect.
3. **Scope justification** (paste into the Cloud Console form for each
   scope):
   - `youtube.upload`: "Lets the signed-in creator publish videos to their
     own channel directly from CreatorOS's content workflow, only on
     explicit user action. Every automated publish also passes an in-app
     safety gate before anything is uploaded."
   - `yt-analytics.readonly`: "Reads the signed-in creator's own channel
     analytics (views, watch time, retention, traffic sources) so
     CreatorOS can show accurate, non-fabricated performance dashboards —
     this data is not available through the public Data API."
   - `youtube.readonly`: usually pre-approved / low friction, but justify as
     "Reads the signed-in creator's own channel and video metadata to power
     the content-planning dashboard."
4. **Demo video** (see script below) — record, upload **unlisted** to
   YouTube, paste the link into the consent screen form.
5. Click **Submit for verification** from the OAuth consent screen page.
   Typical turnaround for this scope tier: a few days to a couple of weeks.
   Google may email follow-up questions — answer from the same honest
   framing as the privacy policy (no fabricated capabilities).

## Demo video script

Google's reviewers watch this to confirm the app does what it claims and
uses each sensitive scope visibly. Keep it under ~5 minutes, screen
recording with narration (your voice explaining each step out loud —
silent screen captures are usually rejected).

**Before recording:** use a real Google account you control that is
already added as a Test user, since Production isn't approved yet.

1. **Intro (10–15s)** — "This is CreatorOS, a YouTube creator-intelligence
   tool. I'm going to show how it connects to a creator's own YouTube
   channel and what it does with that access."
2. **Sign in to CreatorOS** — show the CreatorOS login screen, sign in.
3. **Navigate to Channels page** — narrate: "To get authorized analytics
   and publishing, I connect my channel via Google OAuth."
4. **Click "Connect with Google"** — let the full Google consent screen
   render on camera. Narrate what's being requested: "Google is asking me
   to confirm CreatorOS can read my channel's videos and analytics, and
   publish on my behalf." Click Allow.
5. **Land back on Channels page** — show the channel now appears connected
   with real data (title, subscriber count).
6. **Show `youtube.readonly` in use** — open the Dashboard or a channel
   detail view; narrate that the video list/metadata shown comes from the
   Data API read.
7. **Show `yt-analytics.readonly` in use** — open the Analytics page;
   narrate: "These view counts, retention, and traffic-source numbers come
   directly from YouTube Analytics for my own channel — CreatorOS never
   fabricates a number; anything it can't verify is labeled as estimated
   or insufficient data" (point at a real screen showing this labeling).
8. **Show `youtube.upload` in use** — open Publishing/Distribution, walk
   through creating or viewing a publishing run; narrate: "Every publish
   passes a safety gate before anything is uploaded, and I can stop
   automated publishing at any time from the Control Center kill switch."
   Show the Settings/Control Center emergency-stop toggle on camera.
9. **Close (10s)** — "That's the full flow: a creator connects their own
   channel, CreatorOS reads their own analytics, and publishes only with
   their explicit control." Optionally show the `/privacy` page URL in the
   address bar.

Upload unlisted (not private — Google's reviewer needs the link to work
without requesting access), and paste the URL into the consent screen form
alongside the scope justifications above.
