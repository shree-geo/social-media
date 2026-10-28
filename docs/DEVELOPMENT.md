# Development

## Prerequisites

- Docker with Compose v2.24+
- For running tools outside Docker: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node.js 20.9+ (22 LTS recommended)

## First run

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                # → JWT_SECRET
python3 -c "import os,base64; print('v1:' + base64.b64encode(os.urandom(32)).decode())"       # → ENCRYPTION_KEYS

docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The `migrate` service runs `alembic upgrade head` and then `python -m app.cli seed` (permissions, system roles, bootstrap platform admin) before the backend, worker and beat start.

On the very first run, the seed creates the platform super admin from `BOOTSTRAP_ADMIN_EMAIL` and prints a **temporary password once**:

```bash
docker compose logs migrate
```

Log in at http://localhost:8080/admin/login and set your own password; the temporary one expires after 7 days. SME owners log in at http://localhost:8080/login.

PostgreSQL roles (`app_owner`, `app_runtime`, `app_platform`) are created by `infra/postgres/init/01-roles.sh` **only when the data volume is first created**. After changing role passwords in `.env`, recreate the volume:

```bash
docker compose down -v      # deletes local data
```

## Services and ports (dev)

All host ports bind to `127.0.0.1` and can be changed in `.env` if they clash with other projects.

| Service | URL / port | Notes |
|---|---|---|
| nginx | http://localhost:8080 (`HTTP_PORT`) | single entry point: `/` → frontend, `/api` and `/health` → backend |
| backend | via nginx | FastAPI with `--reload`; source bind-mounted |
| frontend | via nginx | `next dev`; source bind-mounted |
| worker | — | Celery, all queues, solo pool |
| beat | — | Celery beat (exactly one) |
| postgres | localhost:5442 (`DEV_POSTGRES_PORT`) | owner: `app_owner` |
| redis | localhost:6381 (`DEV_REDIS_PORT`) | |
| storage | http://localhost:8343 (`DEV_S3_PORT`) | S3-compatible API (SeaweedFS); keys = `S3_ACCESS_KEY`/`S3_SECRET_KEY` |
| mailpit | http://localhost:8035 (`DEV_MAILPIT_PORT`) | captured outgoing email |

## Backend without Docker

```bash
cd backend
uv sync
# point the URLs at localhost (postgres/redis from the dev compose file)
export DATABASE_URL=postgresql+asyncpg://app_runtime:change-me-runtime@localhost:5442/socialcommerce
export DATABASE_PLATFORM_URL=postgresql+asyncpg://app_platform:change-me-platform@localhost:5442/socialcommerce
export DATABASE_MIGRATION_URL=postgresql+asyncpg://app_owner:change-me-owner@localhost:5442/socialcommerce
export REDIS_URL=redis://localhost:6381/0 CELERY_BROKER_URL=redis://localhost:6381/1

uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run celery -A app.workers.celery_app worker -Q webhooks,outbound,media,default,pdf --pool=solo
```

## Checks

```bash
cd backend
uv run pytest                 # unit tests (no services needed)
uv run pytest -m integration  # needs the dev postgres running; creates/drops <db>_test
uv run ruff check . && uv run ruff format --check .
uv run mypy app

cd frontend
npm run lint
npm run build
```

## Migrations

```bash
cd backend
uv run alembic revision -m "short description"      # write upgrade/downgrade by hand (RLS, grants)
uv run alembic upgrade head
uv run alembic downgrade -1
```

Rules:

- Migrations run as `app_owner` (`DATABASE_MIGRATION_URL`). The application never runs DDL.
- Every tenant-owned table gets RLS enabled + forced and the `tenant_isolation` policy in the same migration that creates it (see `DATABASE.md` §3).
- Migrations must be backward compatible with the previous app version (expand → migrate → contract).

## Meta webhooks locally

Meta must reach a public HTTPS URL. Use a tunnel (Cloudflare Tunnel or ngrok) to `http://localhost:8080` and configure the callback URLs from `ONBOARDING_AND_CHANNEL_SETUP.md` §2 in the Meta app dashboard.
