# Operations

## Health checks

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness — process is up. No dependency checks. |
| `GET /ready` | Readiness — verifies the database is reachable. |
| `GET /metrics` | Minimal Prometheus-text metrics (DB pool usage). |

Docker Compose's healthchecks poll `/health` for the backend and an
equivalent HTTP check for the frontend; `depends_on: condition:
service_healthy` ensures Postgres/Redis are actually ready (not just
started) before the backend container runs migrations.

## Background jobs (Celery)

Defined in `backend/app/jobs/tasks.py`, scheduled via
`backend/app/jobs/celery_app.py`'s `beat_schedule`:

| Task | Schedule | Purpose |
|---|---|---|
| `youtube_sync` | on-demand + `sync_all_channels` every 6h | Incremental channel/video sync |
| `trend_refresh` | on-demand + `refresh_all_trends` every 12h | Recompute trend scores |
| `analytics_sync` | on-demand | Capture an analytics snapshot |
| `recommendation_refresh` | on-demand | Regenerate Next Best Video |
| `report_generation` | on-demand | Queue a weekly-report notification |
| `temporary_media_cleanup_job` | hourly | Delete `storage/tmp_uploads/*` older than 24h |
| `run_daily_growth_agent` | daily | Compose "Today's Top 5 Growth Actions" from the growth diagnostic |

Every task wraps itself in a `jobs` table row (`app.jobs.models.Job`) for
observability, with `idempotency_key` preventing duplicate runs and
Celery's own `max_retries`/`default_retry_delay` handling transient
failures with backoff.

Watch the worker: `docker compose logs -f worker`.

## VPS storage optimization

CreatorOS is explicitly designed to **not** become a permanent video
storage server (per the Growth OS addendum). Raw video files pass through
`storage/tmp_uploads/` only transiently during an upload-to-YouTube flow;
`temporary_media_cleanup_job` deletes anything older than 24 hours there.
Permanent data is metadata/analytics (in Postgres), never the raw media
itself. Never point application code at `storage/` for anything meant to
persist — that's what the database is for.

## Autonomous Control Center & kill switch

`GET/POST /api/v1/settings/kill-switch/*` and
`GET /api/v1/settings/control-center` (also the `/settings` frontend page)
surface:

- Whether autonomous publishing is currently stopped, and why.
- Connected channels, active publishing rules, pending/completed/failed
  publishing runs.

Activating the kill switch (`POST /kill-switch/activate`) blocks every
*new* `AUTHORIZED_AUTONOMOUS`-mode publishing action from starting (the
safety gate checks it — see `docs/security.md`). It does not cancel work
already in flight and never deletes data. Deactivate with
`POST /kill-switch/deactivate`.

## Logs

Structured JSON via `structlog` (`app/core/logging.py`), one line per HTTP
request (method, path, status, duration, request_id) plus explicit
`logger.info`/`.warning`/`.error` calls in services for AI generation
attempts, sync failures, etc. In Docker: `docker compose logs -f backend`.
On a bare VPS: whatever your process manager captures on stdout
(journalctl if run under systemd).

## Rotating secrets

1. Generate a new `JWT_SECRET` — this immediately invalidates every
   existing access/refresh token; all users must log in again.
2. Generate a new `ENCRYPTION_KEY` **carefully**: existing
   `oauth_*_token_encrypted` values were encrypted with the old key and
   will fail to decrypt. Either re-run OAuth for every connected channel
   after rotating, or decrypt-then-re-encrypt those columns in a
   maintenance migration before switching the key.

## Common maintenance commands

```bash
docker compose exec backend alembic current       # current migration
docker compose exec backend alembic history       # migration history
docker compose exec postgres psql -U creatoros    # direct DB access
docker compose restart worker                     # restart just the worker
```
