# Architecture

## Overview

CreatorOS is a monorepo with three deployable units — a FastAPI backend, a
Celery worker/beat pair, and a Next.js frontend — sharing one PostgreSQL
database and one Redis instance.

```
                    ┌─────────────┐
   Browser ───────► │    Nginx    │
                    └──────┬──────┘
                     ┌─────┴─────┐
                     ▼           ▼
             ┌───────────┐  ┌──────────┐
             │  Next.js  │  │ FastAPI  │
             │ (frontend)│  │ (backend)│
             └───────────┘  └────┬─────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              ┌──────────┐  ┌─────────┐  ┌────────────┐
              │PostgreSQL│  │  Redis  │  │  Ollama /  │
              │          │  │(broker) │  │  OpenAI    │
              └──────────┘  └────┬────┘  └────────────┘
                                  ▼
                          ┌───────────────┐
                          │ Celery worker │
                          │  + beat       │
                          └───────────────┘
```

## Backend layout (`backend/app/`)

```
app/
  core/        Config, security, crypto, logging, errors, data-quality
               vocabulary, generic CRUD helpers, timezone helpers.
  db/          SQLAlchemy Base, async session, cross-dialect GUID type,
               models_registry (imports every model for Alembic).
  ai/          AIOrchestrator + AIProvider implementations (Ollama,
               OpenAI-compatible). The ONLY place that talks to an LLM.
  jobs/        Celery app, task definitions, kill switch, Job/KillSwitch
               models.
  modules/     One package per domain (auth, channels, videos,
               competitors, trends, topics, research, hooks, titles,
               scripts, thumbnails, seo, content, analytics, retention,
               experiments, recommendations, notifications, audit,
               publishing, distribution, settings, users). Each module
               owns its own models.py / schemas.py / service.py /
               router.py.
```

Every module follows the same internal shape:

- **models.py** — SQLAlchemy ORM tables.
- **schemas.py** — Pydantic request/response contracts (never expose ORM
  models directly).
- **service.py** — business logic; the only layer allowed to touch the
  database or call a provider.
- **router.py** — thin FastAPI routes: validate input, call service, map
  to a schema. No business logic lives here.

## Provider abstraction pattern

Two external-system boundaries are abstracted the same way, on purpose:

1. **YouTube** — `app/modules/channels/providers/base.py` defines
   `YouTubeProvider`. `MockYouTubeProvider` backs local dev/tests;
   `YouTubeDataAPIProvider` is the real implementation over YouTube Data
   API v3 + Analytics v2, built on plain `httpx` (no SDK). Nothing outside
   this package imports Google APIs directly.
2. **AI** — `app/ai/providers/base.py` defines `AIProvider`.
   `OllamaProvider` and `OpenAICompatProvider` are the two implementations.
   `AIOrchestrator` (`app/ai/orchestrator.py`) is the only thing business
   logic calls; it handles structured-output validation, retries, and
   provider fallback.

A third boundary, **distribution to non-YouTube platforms**
(`app/modules/distribution/providers/`), follows the identical pattern —
`DistributionProvider` interface, `YouTubeDistributionProvider` as the one
real implementation (it delegates to the *same* `YouTubeProvider`, not a
second integration), and `NotConfiguredProvider` for Instagram/Facebook/X/
LinkedIn until their own OAuth app review is completed by a human.

## Data-integrity pattern

`app/core/data_quality.py` defines `Metric[T]`: every computed number in the
system is wrapped in `{value, quality, sample_size, reason, source,
computed_at}` where `quality` is `REAL | ESTIMATED | INSUFFICIENT_DATA`.
Services return `insufficient_data(...)` instead of guessing whenever a
minimum sample-size threshold isn't met. The frontend's `MetricCard`
component renders this state explicitly rather than showing a blank or
zero value.

## Growth OS extensions

The Growth OS addendum's features were built as extensions of existing
modules, not parallel systems:

| Growth OS concept | Lives in | Extends |
|---|---|---|
| Subscriber growth metrics, growth scorecard, channel diagnostic | `app/modules/analytics/` | Analytics engine |
| Next Best Video (multi-score) | `app/modules/recommendations/` | Recommendation engine |
| Publishing safety gate, state machine, kill switch | `app/modules/publishing/`, `app/jobs/kill_switch.py` | Channel/YouTubeProvider |
| Distribution orchestrator, platform assets | `app/modules/distribution/` | Content/Shorts concept |
| Daily growth agent | `app/jobs/tasks.py:run_daily_growth_agent` | Analytics + notifications |
| Autonomous Control Center | `app/modules/settings/` | Publishing + kill switch |

## Frontend layout (`frontend/src/`)

- `app/` — Next.js App Router pages, one folder per route, all client
  components (no server actions/RSC data fetching — the API is the single
  source of truth, called from the browser).
- `lib/api.ts` — fetch wrapper with automatic access-token refresh on 401.
- `lib/auth-context.tsx` — React context holding the current user.
- `components/app-shell.tsx` — sidebar navigation + auth gate.
- `components/metric-card.tsx` — the data-quality rendering pattern.

## Why these choices

- **httpx over the Google API client / SDKs**: smaller dependency surface,
  every HTTP call is visible and testable, no generated-code magic.
- **SQLAlchemy 2 async + a cross-dialect GUID type**: production runs on
  PostgreSQL; the test suite runs on SQLite in-memory for speed. The same
  models work on both without a test-only model duplication.
- **Celery over a lighter queue**: it's what the spec named explicitly, and
  its retry/backoff/dead-letter primitives map directly onto the
  publishing safety gate's idempotency requirements.
