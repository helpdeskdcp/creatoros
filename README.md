# CreatorOS

**CreatorOS** is a YouTube Creator Intelligence and Content Operating System. It
turns raw channel, video, and competitor data into an explainable pipeline of
opportunities, scripts, and recommendations — and learns from what actually
happens after you publish.

> Status: active development. See [`docs/FINAL_AUDIT.md`](docs/FINAL_AUDIT.md)
> for exactly what is implemented, tested, and still pending versus this
> document's long-term vision.

## Pipeline

```
Channel Data → Video Data → Competitor Data → Trend Detection
  → Topic Opportunity Engine → Research Engine → Content Strategy
  → Hook Engine → Title Engine → Script Engine → Shorts Engine
  → Thumbnail Intelligence → SEO Engine → Content Workflow → Publishing
  → Analytics → Retention/CTR Analysis → Outcome Learning
  → Next Content Recommendation
```

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 15 |
| Cache / queue | Redis 7, Celery |
| Frontend | Next.js (App Router), TypeScript, Tailwind CSS, TanStack Query |
| AI | Provider-abstracted: local Ollama or any OpenAI-compatible API |
| Infra | Docker Compose, Nginx, GitHub Actions |

Business logic never talks to a specific AI or YouTube SDK directly — everything
goes through a provider interface (`app/ai/providers`, `app/modules/channels/providers`)
so swapping vendors never requires touching application code.

## Monorepo layout

```
creatoros/
  backend/        FastAPI app, Alembic migrations, pytest suite
  frontend/       Next.js dashboard
  workers/        Celery worker entrypoint + beat schedule
  infrastructure/ Nginx config, deployment assets
  scripts/        Backup/restore and operational scripts
  docs/           Architecture, ops, and audit documentation
```

## Quickstart (local development)

Requirements: Docker + Docker Compose, or Python 3.11 / Node 20+ / PostgreSQL 15 / Redis 7 installed locally.

```bash
cp .env.example .env
# edit .env — at minimum set JWT_SECRET; YouTube/OpenAI keys are optional
# for local dev (the app runs with mock/local providers without them).

make up          # docker compose up --build -d
make migrate      # run Alembic migrations inside the backend container
make seed         # optional: create a demo OWNER user
```

Backend: http://localhost:8000/docs (OpenAPI)
Frontend: http://localhost:3000

Without Docker:

```bash
make backend-dev   # uvicorn with reload, needs local Postgres+Redis
make worker-dev    # celery worker
make frontend-dev  # next dev
```

## Testing

```bash
make test          # backend pytest suite
make lint          # ruff + mypy
make frontend-test # frontend unit tests
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/installation.md`](docs/installation.md)
- [`docs/deployment.md`](docs/deployment.md)
- [`docs/youtube.md`](docs/youtube.md)
- [`docs/ai.md`](docs/ai.md)
- [`docs/database.md`](docs/database.md)
- [`docs/security.md`](docs/security.md)
- [`docs/testing.md`](docs/testing.md)
- [`docs/operations.md`](docs/operations.md)
- [`docs/troubleshooting.md`](docs/troubleshooting.md)
- [`docs/api.md`](docs/api.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/DECISIONS.md`](docs/DECISIONS.md)
- [`docs/FINAL_AUDIT.md`](docs/FINAL_AUDIT.md)

## Data integrity principles

CreatorOS never fabricates analytics, trend scores, CTR, retention, or
competitor statistics. Every analytical result carries `source`, `timestamp`,
and `data_quality`. When a metric can't be computed from real data with a
sufficient sample size, the API returns `INSUFFICIENT_DATA` with an
explanation rather than a guessed number.

## License

MIT — see [LICENSE](LICENSE).
