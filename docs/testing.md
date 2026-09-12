# Testing

## Backend

```bash
cd backend
.venv/bin/pytest -v
```

25 tests, run against an in-memory SQLite database (no external services
required) in ~5 seconds:

| File | Covers |
|---|---|
| `test_auth.py` | Registration (first user → OWNER), duplicate email, wrong password, login/me, protected-route 401, refresh rotation + reuse rejection, logout revocation, RBAC 403 |
| `test_channels_and_videos.py` | Connect + sync via `MockYouTubeProvider`, cross-user 404 isolation, and — the important one — that Channel Intelligence returns `INSUFFICIENT_DATA` for velocity after only one sync (proving the never-fabricate rule holds under real code paths, not just in a unit test of the helper function) |
| `test_ai_orchestrator.py` | Structured-output success, retry-then-succeed on invalid JSON, fallback to a secondary provider, total failure when every provider fails, and schema-validation rejection (a syntactically valid but incomplete JSON object must still fail) |
| `test_publishing_gate.py` | Safety gate blocks on missing OAuth, blocks autonomous mode when not enabled, blocks when the kill switch is active, passes for a valid ASSIST-mode run, and idempotency (two `create_run` calls with the same key return the same row) |
| `test_growth_and_data_quality.py` | `Metric` helper invariants, growth diagnosis returning a note (not a guess) with zero data, subscriber growth returning `INSUFFICIENT_DATA` without authorized analytics |

Also run at every commit boundary:

```bash
.venv/bin/ruff check app tests    # lint — zero warnings as of this writing
.venv/bin/mypy app --ignore-missing-imports
```

### Verified beyond unit tests

During development, the following were exercised against **real**
PostgreSQL and Redis (not mocks), not just the SQLite test suite:

- `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head`
  roundtrip on PostgreSQL 15 (caught and fixed a circular-FK ordering bug
  and a Postgres-ENUM-type-not-dropped bug — see `docs/FINAL_AUDIT.md`).
- `scripts/backup_postgres.sh` → `scripts/restore_postgres.sh` full
  roundtrip into a disposable database.
- Full `docker compose up --build` — all 7 services reaching a healthy
  state, migrations running automatically, Celery worker connecting to its
  Redis broker, and a real HTTP register → connect-channel → sync →
  intelligence flow through both the backend directly and through Nginx.

## Frontend

```bash
cd frontend
npm run typecheck   # tsc --noEmit — zero errors
npm run build       # production build — all 27 routes compile
npm run lint        # eslint
```

No frontend unit-test suite exists yet (`vitest` is wired in
`package.json` but no test files have been written) — see
`docs/ROADMAP.md`. Manual end-to-end verification during development used
direct API calls simulating every page's real request sequence
(register → connect channel → sync → fetch intelligence → growth
diagnosis → control center), documented in the commit history rather than
an automated E2E suite, since a browser-based E2E run requires a browser
on the same host as the app under test — this development session's
browser-automation tool controls the *user's own* local browser, not the
VPS the app runs on.

## What "no fake success" means in this codebase

- No test asserts against a hardcoded expected number that the code
  itself produces via the same formula (that would just test that
  arithmetic works, not that the *behavior* is correct) — assertions
  check quality flags (`INSUFFICIENT_DATA` vs `REAL`), status codes, and
  structural invariants (idempotency, rotation, RBAC).
- No test mocks the database — every backend test hits a real (in-memory)
  SQLAlchemy session running real queries against real tables.
- The AI orchestrator tests use a scripted fake `AIProvider`, not a mock
  of `AIOrchestrator` itself — the retry/fallback/validation *logic* under
  test is real; only the network call is faked.
