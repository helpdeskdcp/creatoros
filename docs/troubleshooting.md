# Troubleshooting

## "address already in use" when starting the backend/frontend

Another application on the host is already using the default port. This
happened during CreatorOS's own development on a shared VPS (an unrelated
gunicorn app already held port 8000). Fix: set `BACKEND_PORT` /
`FRONTEND_PORT` / `POSTGRES_PORT` / `REDIS_PORT` / `NGINX_PORT` in `.env`
to free ports, or find and stop the conflicting process (`ss -tlnp | grep
<port>`) if it's actually meant to be CreatorOS's.

## `alembic upgrade head` fails with "type ... already exists"

You likely ran `alembic downgrade base` and then `upgrade head` again
without the ENUM-type cleanup in `downgrade()` — see
`docs/database.md`. Fix by manually dropping the leftover types
(`SELECT typname FROM pg_type WHERE typtype='e'` to list them,
`DROP TYPE IF EXISTS <name> CASCADE` to remove) or restoring from a backup.

## Migration references `app.db.types.GUID()` but `NameError: name 'app' is not defined`

The Alembic env.py's custom `_render_item` hook wasn't in place when the
migration was generated. It's already fixed in `migrations/env.py` — if
you see this on a *new* migration, check you didn't accidentally revert
that hook.

## `TypeError: can't compare offset-naive and offset-aware datetimes`

SQLite (used by the test suite) drops timezone info on datetimes;
PostgreSQL doesn't. Any comparison between a DB-loaded datetime and
`datetime.now(UTC)` must go through `app.core.timeutils.ensure_aware()`
first. This was hit and fixed in four places during development
(`auth/service.py`, `videos/service.py`, `channels/service.py`,
`publishing/service.py`) — if you add a new datetime comparison against a
DB-loaded field, wrap it the same way.

## AI generation endpoints return 500 / `AIOrchestratorError`

- Check Ollama is running and reachable: `curl http://localhost:11434/api/tags`.
- Check `OLLAMA_MODEL` in `.env` matches a model you've actually pulled
  (`ollama list`).
- If using `AI_PRIMARY_PROVIDER=openai`, check `OPENAI_API_KEY` is set and
  valid.
- The orchestrator retries on invalid JSON before giving up — persistent
  failures usually mean the model can't follow the schema; try a larger
  model or reduce `max_tokens`/simplify the prompt in that module's
  `service.py`.

## Channel sync returns real-looking data but I haven't configured YouTube credentials

That's `MockYouTubeProvider` — expected behavior without
`YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET` set. See `docs/youtube.md`.

## `docker compose up` succeeds but the frontend can't reach the backend

Check `NEXT_PUBLIC_API_BASE_URL` was set at **build time** (it's baked into
the static JS bundle, not read at runtime) — rebuild the frontend image
after changing it: `docker compose build frontend && docker compose up -d frontend`.

## Redis `NOAUTH Authentication required`

If deploying alongside other apps that share a Redis instance with a
password set, CreatorOS's own `docker-compose.yml` Redis container has no
auth by default (it's a private, CreatorOS-only container on its own
Docker network) — don't point `REDIS_URL`/`CELERY_BROKER_URL` at a shared
host Redis unless you also set its password in the connection URL.
