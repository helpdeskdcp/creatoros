# YouTube Integration

## Architecture

All YouTube access goes through the `YouTubeProvider` interface
(`backend/app/modules/channels/providers/base.py`). There is exactly one
production implementation (`YouTubeDataAPIProvider`, plain `httpx` over
YouTube Data API v3 + YouTube Analytics API v2) and one test/dev
implementation (`MockYouTubeProvider`, deterministic fixture data — no
network calls). `app/modules/channels/providers/__init__.py:get_youtube_provider()`
picks between them automatically based on whether `YOUTUBE_CLIENT_ID`/
`YOUTUBE_CLIENT_SECRET` are set.

**Never** import `httpx`/Google APIs directly outside this package.
**Never** create a second YouTube integration for a different feature
(publishing, distribution) — extend the same provider (see
`app/modules/distribution/providers/youtube_provider.py`, which delegates
to this same interface rather than duplicating it).

## Setting up real OAuth credentials

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   create an OAuth 2.0 Client ID (type: Web application).
2. Enable the **YouTube Data API v3** and **YouTube Analytics API** for the
   project.
3. Add an authorized redirect URI matching `YOUTUBE_REDIRECT_URI` in your
   `.env` (default: `http://localhost:8000/api/v1/channels/oauth/callback`).
4. Set in `.env`:
   ```
   YOUTUBE_CLIENT_ID=...
   YOUTUBE_CLIENT_SECRET=...
   YOUTUBE_REDIRECT_URI=https://your-domain/api/v1/channels/oauth/callback
   YOUTUBE_API_KEY=...   # optional, raises quota for public (unauthenticated) reads
   ```
5. Restart the backend. `get_youtube_provider()` will now return
   `YouTubeDataAPIProvider` instead of the mock.

Without these variables set, CreatorOS runs entirely on
`MockYouTubeProvider` — every endpoint still works end-to-end for
development, demos, and the test suite, but returns fixture data instead of
real channel data.

## What requires OAuth vs. what doesn't

| Capability | Requires OAuth |
|---|---|
| Connect a channel by public ID, sync public stats/videos | No (`POST /api/v1/channels`) |
| Channel Intelligence (views, engagement, velocity) | No — computed from public data |
| CTR, retention curves, subscriber attribution | **Yes** — YouTube Analytics API only exposes these to the channel's authorized owner |
| Publishing / uploading video | **Yes** — `youtube.upload` scope |

Endpoints that need authorized data return `INSUFFICIENT_DATA` with an
explanatory reason rather than guessing when a channel hasn't completed
OAuth — see `docs/security.md` and the Data Integrity Rule in the README.

## Publishing

`YouTubeProvider` also defines the upload/publish surface
(`prepare_upload`, `upload_video`, `set_thumbnail`,
`check_processing_status`, `verify_publication`) using YouTube's resumable
upload protocol. This is wrapped by `app/modules/publishing/` — a
13-step safety gate, an idempotent state machine, and a creator-controlled
kill switch — before any of these methods are ever called automatically.
See `docs/operations.md` for the safety-gate walkthrough.

## Other distribution platforms (Instagram / Facebook / X / LinkedIn)

`app/modules/distribution/providers/base.py` defines a generic
`DistributionProvider` interface mirroring `YouTubeProvider`'s shape. Only
YouTube is wired to a real implementation in this codebase — each other
platform requires:

1. Registering a developer app with that platform.
2. Completing that platform's own app-review/business-verification process
   (this is a human, per-organization step CreatorOS cannot automate).
3. Implementing a `<Platform>DistributionProvider` against that platform's
   API, following `youtube_provider.py` as the template.

Until that's done, `get_distribution_provider()` returns a
`NotConfiguredProvider` for those platforms — every method raises a clear
`DistributionProviderError` rather than silently no-opping or pretending to
publish successfully.
