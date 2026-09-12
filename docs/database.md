# Database

## Schema

37 tables, defined across each module's `models.py` and aggregated in
`app/db/models_registry.py` (the only module Alembic's `env.py` imports —
always import new models there too, or `alembic revision --autogenerate`
won't see them).

Core groups:

- **Identity**: `users`, `sessions`
- **Channel data**: `channels`, `videos`, `video_metrics`
- **Competitor intelligence**: `competitors`, `competitor_videos`
- **Trend/topic engine**: `trends`, `topics`, `opportunities`
- **Research**: `research_projects`, `research_sources`
- **Generation**: `hooks`, `titles`, `scripts`, `script_versions`,
  `thumbnail_briefs`, `seo_records`
- **Workflow**: `content_items`, `content_events`
- **Analytics / Growth OS**: `analytics_snapshots`,
  `subscriber_growth_metrics`, `growth_scores`, `growth_actions`,
  `retention_metrics`
- **Recommendations & experiments**: `recommendations`, `experiments`,
  `experiment_variants`
- **Publishing & distribution**: `publishing_rules`, `publishing_runs`,
  `publishing_attempts`, `distribution_campaigns`, `distribution_assets`
- **Operations**: `notifications`, `jobs`, `kill_switches`, `audit_logs`

All primary keys are UUIDs (`app.db.types.GUID` — a cross-dialect type:
native `UUID` on PostgreSQL, `CHAR(36)` on SQLite so the test suite can use
an in-memory database). All tables carry `created_at`/`updated_at` except
`audit_logs` (append-only, `created_at` only) and pure join-ish tables.

## Migrations

Alembic, configured in `backend/alembic.ini` /
`backend/migrations/env.py`. Two things env.py does beyond the Alembic
default that matter if you touch it:

1. **Custom type rendering** (`_render_item`) — without this,
   autogenerate emits `app.db.types.GUID()` without importing `app`,
   which crashes every migration. Already handled; don't remove it.
2. **Async engine** — `run_migrations_online()` uses
   `async_engine_from_config` since the app is async-first.

Generate a migration after changing models:

```bash
cd backend
alembic revision --autogenerate -m "describe the change"
```

**Always review the generated file.** In particular, if you add an enum
column, add its type name to the list at the bottom of the initial
migration's `downgrade()` (or your new migration's, if adding a new enum
later) — PostgreSQL ENUM types are not automatically dropped by
`drop_table()`, and skipping this breaks `downgrade` → `upgrade` roundtrips
(this was caught and fixed during initial development; see
`docs/FINAL_AUDIT.md`).

Apply:

```bash
alembic upgrade head
```

The backend Docker image runs this automatically on container start.

### Verified

The initial migration was generated against, applied to, and both
upgraded *and downgraded* on a real PostgreSQL 15 instance (not just
SQLite) during development — including the full
`upgrade → downgrade → upgrade` roundtrip — to catch exactly the kind of
issue described above before it could reach production.

## Backups

```bash
make backup    # scripts/backup_postgres.sh — pg_dump, gzip, timestamped file in ./backups
make restore FILE=backups/creatoros_20260101_000000.sql.gz
```

`restore_postgres.sh` requires typing the target database name to confirm
before touching anything — it is a destructive operation by design. No
automatic backup deletion/retention policy exists; that's a deliberate
choice per the spec ("never delete old backups without an explicit
retention policy") — set one up via cron + your own retention rule.

## Data integrity by construction

See `app/core/data_quality.py`. Every analytics/scoring table stores enough
to reconstruct *why* a number is what it is: `sample_size`, and either an
`explanation`/`reason` text field or a `data_quality` enum column. Nothing
in the schema has a "confidence" or "score" column without a paired
sample-size or explanation column next to it.
