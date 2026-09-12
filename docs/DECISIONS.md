# Architecture Decisions

Short log of decisions made where the spec left room for judgment, and why.

## httpx over google-api-python-client for YouTube

The original dependency plan included `google-api-python-client` and
`google-auth-oauthlib`. Dropped in favor of raw `httpx` calls to the
documented REST endpoints (OAuth token endpoint, Data API v3, Analytics
API v2, resumable upload protocol). Reasoning: smaller dependency surface,
every request/response is visible in `youtube_data_api.py` rather than
hidden behind generated client code, and it matches the same pattern
already used for the AI providers — easier to reason about and test.

## Growth OS additions extend existing modules, not new parallel systems

The Growth OS addendum arrived after the core spec was already being
built. Per its own explicit instruction ("search for an existing
equivalent... extend it... do not create duplicate implementations"),
every addition was placed inside the module it most naturally extends
(subscriber growth → `analytics`; Next Best Video scores →
`recommendations`; publishing safety → `channels`/a new `publishing`
module that wraps the existing `YouTubeProvider` rather than duplicating
it). See the table in `docs/architecture.md`.

## Multi-platform distribution: interface now, one real implementation

Instagram/Facebook/X/LinkedIn publishing was requested, but each requires
a human to register and get approved for a developer app on that
platform — not something achievable inside this session. Built the full
`DistributionProvider` interface and orchestrator so adding a real
implementation later requires no architectural change, shipped
`NotConfiguredProvider` for the unauthorized platforms (raises clearly
rather than silently no-opping), and documented the exact remaining step
per platform in `docs/youtube.md`.

## Growth/publishing endpoints live under `/analytics/growth/*` and
`/publishing/*`, not a bare top-level `/growth/*`

The addendum suggested `/api/v1/growth/overview`, `/growth/diagnosis`,
etc. as "potential additions." Its own higher-priority rule ("extend
existing... do not create parallel duplicate systems") took precedence
over the exact suggested path spelling — growth diagnostics/scorecard/
subscriber metrics are computed *by* the analytics engine from the same
underlying data, so they're routed as `/analytics/growth/{channel_id}/...`
to make that relationship explicit in the API surface itself, rather than
implying a separate "growth service" exists.

## Next.js pinned to 15.5.25 / React 19, not the originally-planned 14.2.x

`npm install` with the initially-planned Next.js 14.2.18 surfaced 2
critical + 5 high severity CVEs via `npm audit` (including an
unauthenticated RCE advisory). Upgraded to the latest patched stable
release line (15.5.25, with React 19 as its peer requirement) rather than
patching within 14.x, since several of the fixes only landed in 15.x.
Verified the full app still builds and typechecks cleanly after the
upgrade before proceeding. See `docs/security.md`.

## SQLite for tests, PostgreSQL for everything else

Rather than requiring a running Postgres for the unit test suite (slower,
adds CI setup burden), models use a cross-dialect `GUID` type
(`app/db/types.py`) so the identical model definitions run against
in-memory SQLite in tests and real PostgreSQL in dev/production. This
surfaced a real bug (SQLite drops timezone info on datetimes) during
development — see `docs/troubleshooting.md` — which was worth catching in
a 5-second test run rather than in production.

## First registered user becomes OWNER

No invite-only flow exists yet. The simplest way to bootstrap a working
RBAC system without a separate admin-provisioning step: the first
`/auth/register` call in a fresh database gets `OWNER`; every subsequent
registration defaults to `VIEWER` and must be promoted by an admin. This
is a deliberate simplification for self-hosted single-tenant use, not a
multi-tenant SaaS invite system.
