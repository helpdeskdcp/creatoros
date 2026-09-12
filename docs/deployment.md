# Deployment

## Isolated deployment on a shared VPS

CreatorOS is designed to coexist with unrelated applications on the same
host. All service names are prefixed `creatoros-*`
(`creatoros-backend`, `creatoros-worker`, `creatoros-beat`,
`creatoros-frontend`, `creatoros-postgres`, `creatoros-redis`,
`creatoros-nginx`), all ports are configurable via `.env`, and the Docker
Compose project lives entirely under this repository's directory —
`docker compose down` never touches anything outside it.

**Before deploying**, check which ports are already taken on the host:

```bash
ss -tlnp | grep -E ':(8000|3000|5432|6379)\b'
```

If any are in use by another application, set the corresponding `*_PORT`
variable in `.env` to a free port before `make up`.

## Production checklist

1. Generate real secrets (`JWT_SECRET`, `ENCRYPTION_KEY`) — never reuse the
   `.env.example` placeholders.
2. Set `ENVIRONMENT=production`, `COOKIE_SECURE=true`, and a real
   `COOKIE_DOMAIN`.
3. Configure `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/
   `YOUTUBE_REDIRECT_URI` for OAuth (see `docs/youtube.md`).
4. Put a TLS-terminating reverse proxy (host Nginx, Caddy, or a cloud LB)
   in front of the `nginx` container — `infrastructure/nginx/creatoros.conf`
   is HTTP-only by design and expects TLS to already be terminated.
5. Run `make migrate` (or let the backend container's entrypoint run it
   automatically) before traffic hits a new version.
6. Set up `scripts/backup_postgres.sh` on a cron schedule (see
   `docs/operations.md`).
7. Point `docker-compose.yml`'s Postgres/Redis volumes at durable storage.

## Deploying an update

```bash
git pull
docker compose build backend worker beat frontend
docker compose up -d
```

The backend container's entrypoint runs `alembic upgrade head` before
starting `uvicorn`, so schema migrations apply automatically on every
deploy. Roll back a bad migration with:

```bash
docker compose exec backend alembic downgrade -1
```

## Verifying a deployment

```bash
curl https://your-domain/health          # {"status":"ok"}
curl https://your-domain/api/v1/openapi.json | head -c 200
docker compose ps                        # all services "healthy"
docker compose logs -f --tail=100 worker # Celery connected to Redis
```

## What this repository does NOT automate

- TLS certificate provisioning (use certbot/your platform's managed TLS).
- DNS.
- Horizontal scaling / multi-node orchestration (Compose is single-host by
  design; for multi-node, translate `docker-compose.yml` into your
  orchestrator of choice — the container images are already
  environment-variable configured for this).
