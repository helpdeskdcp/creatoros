# Installation

## Requirements

- Docker + Docker Compose (recommended path), **or**
- Python 3.11+, Node.js 20+, PostgreSQL 15, Redis 7 installed locally

## Option A — Docker Compose (recommended)

```bash
git clone <your-fork-url> creatoros
cd creatoros
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

Everything else has a working default for local development — YouTube and
OpenAI credentials are optional; the app runs against `MockYouTubeProvider`
and local Ollama without them.

```bash
make up        # docker compose up --build -d
```

Migrations run automatically on backend container start. Verify:

```bash
curl http://localhost:8000/health   # {"status":"ok"}
curl http://localhost:8000/ready    # {"status":"ok","database":true}
```

Frontend: http://localhost:3000
API docs: http://localhost:8000/docs

Create a first account by registering through the UI or:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-strong-password-here"}'
```

The **first** registered user automatically becomes `OWNER`.

## Option B — without Docker

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # edit DATABASE_URL/DATABASE_URL_SYNC for your local Postgres
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload

# Worker (separate terminal)
.venv/bin/celery -A app.jobs.celery_app worker --loglevel=INFO

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Ports used by default

| Service | Port |
|---|---|
| Backend | 8000 |
| Frontend | 3000 |
| Postgres | 5433 (host) → 5432 (container) |
| Redis | 6380 (host) → 6379 (container) |
| Nginx | 8080 |

Every port is overridable via `.env` (`BACKEND_PORT`, `FRONTEND_PORT`,
`POSTGRES_PORT`, `REDIS_PORT`, `NGINX_PORT`) — useful when another
application on the same host already uses the defaults.

## Local AI (Ollama)

CreatorOS defaults `AI_PRIMARY_PROVIDER=ollama`. Install Ollama and pull a
model:

```bash
ollama pull qwen3-mini   # or any chat-capable model
```

Set `OLLAMA_MODEL` in `.env` to match. Every AI-generation endpoint (hooks,
titles, scripts, SEO, thumbnail briefs, Next Best Video) works against this
with zero external API cost. Set `AI_FALLBACK_PROVIDER=openai` and
`OPENAI_API_KEY` if you want automatic fallback when Ollama is unreachable.

## Running tests

```bash
make test          # backend: pytest (SQLite in-memory, no external services needed)
make lint          # backend: ruff + mypy
make frontend-build # frontend: production build + typecheck
```
