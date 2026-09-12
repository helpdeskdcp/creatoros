.PHONY: up down logs migrate seed backend-dev worker-dev frontend-dev test lint format \
        frontend-test backup restore build-ci

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python -m scripts.seed_demo_user

backend-dev:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker-dev:
	cd backend && celery -A app.jobs.celery_app worker --loglevel=INFO --concurrency=2

frontend-dev:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest -v

lint:
	cd backend && ruff check app tests && mypy app --ignore-missing-imports

format:
	cd backend && ruff format app tests

frontend-test:
	cd frontend && npm test

frontend-build:
	cd frontend && npm run build

backup:
	bash scripts/backup_postgres.sh

restore:
	bash scripts/restore_postgres.sh $(FILE)
