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

## Changing the look (theme, fonts, brand)

All colors, fonts, type sizes and corner radii live in **one file**: `frontend/src/styles/theme.css`.

| To change | Edit |
|---|---|
| Brand / accent / status colors | `--sc-*` values in section 1 (light) and section 2 (dark) |
| Sidebar colors (business app / admin console) | `--sc-nav-*` and `--sc-admin-nav-bg` in sections 1 and 2 |
| Font family | `--sc-font-sans` in section 3, and the `@fontsource/...` imports in `frontend/src/app/layout.tsx` |
| Type sizes, line height | `--sc-text-*`, `--sc-leading-*` in section 3 |
| Corner roundness | `--sc-radius-*` in section 3 |
| Product name, login-screen wording | `frontend/src/config/brand.ts` |

Components only use the semantic classes generated from these tokens (`bg-primary`, `text-ink-muted`, `border-line`, `bg-attention` …), never raw hex values or Tailwind's default palette, so editing the tokens restyles the whole app. Dark mode follows the device setting automatically.

## Demo inbox data (development only)

Until WhatsApp/Messenger are connected (Phases 3-4), you can fill a tenant's inbox with sample conversations. They go through the real ingestion pipeline (routing, identity resolution, dedup):

```bash
docker compose exec backend python -m app.cli demo-inbox <owner-email>
```

Replies on the demo channel end as "Not sent" (`channel_unavailable`) because it has no real provider connection. The command refuses to run unless `APP_ENV=development`.

## Celery code changes

The API reloads on file changes; **Celery worker and beat do not**. After adding or changing tasks:

```bash
docker compose restart worker beat
```

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

## Connecting a real Facebook Page (Messenger)

Messenger switches on automatically when these are set in `.env` (then `docker compose restart backend worker beat`):

```env
META_APP_ID=...                      # Meta app (Business type) with Messenger + Facebook Login for Business
META_APP_SECRET=...
META_GRAPH_API_VERSION=v23.0         # the version your Meta app dashboard shows; pin it
META_WEBHOOK_VERIFY_TOKEN=...        # any long random string; also typed into the Meta dashboard
META_LOGIN_CONFIG_ID_MESSENGER=...   # Facebook Login for Business configuration with the permissions below
```

In the Meta app dashboard:

1. **Facebook Login for Business → Configurations**: create one with `pages_show_list`, `pages_messaging`, `pages_manage_metadata`; copy its ID into `META_LOGIN_CONFIG_ID_MESSENGER`. Add your local/tunnel domain to *Allowed domains for the JavaScript SDK*.
2. **Messenger → Webhooks**: callback URL `https://<tunnel>/api/v1/webhooks/messenger`, verify token = `META_WEBHOOK_VERIFY_TOKEN`, fields `messages, message_echoes, message_deliveries, message_reads, messaging_postbacks`.
3. **App settings → Advanced**: *Deauthorize callback* `https://<tunnel>/api/v1/webhooks/meta/deauthorize`, *Data deletion request URL* `https://<tunnel>/api/v1/webhooks/meta/data-deletion`.
4. While the app is in development mode, only people with a role on the app (admins, developers, testers) can connect Pages — add the test Facebook account there.

Then log in as a business Owner → **Channels → Connect Facebook Page**. Customer names on Messenger need Meta's User Profile access; without it new customers show as "Unknown customer" until renamed.

## Connecting a real WhatsApp number

WhatsApp uses the same Meta app and `.env` values as Messenger, plus:

```env
META_LOGIN_CONFIG_ID_WHATSAPP=...    # Facebook Login for Business configuration of type "WhatsApp Embedded Signup"
```

In the Meta app dashboard:

1. Add the **WhatsApp** product. To onboard other businesses' numbers the app must be a **Tech Provider** (business verification + app review for `whatsapp_business_management`, `whatsapp_business_messaging`).
2. **Facebook Login for Business → Configurations**: create an *Embedded Signup* configuration with those two permissions; copy its ID into `META_LOGIN_CONFIG_ID_WHATSAPP`. For "Keep using my WhatsApp Business app", enable coexistence onboarding for the configuration if Meta offers it for your region.
3. **WhatsApp → Configuration → Webhook**: callback `https://<tunnel>/api/v1/webhooks/whatsapp`, same verify token; subscribe to `messages`, `smb_message_echoes`, `phone_number_quality_update`, `phone_number_name_update`, `account_update`.

Then **Channels → Connect WhatsApp**. Use a spare SIM that is not on WhatsApp for the new-number option. If registration fails because of an old two-step verification PIN, remove it in WhatsApp Manager and press *Try again* (the wizard resumes; it doesn't need Meta's window again).

## Meta webhooks locally

Meta must reach a public HTTPS URL. Use a tunnel (Cloudflare Tunnel or ngrok) to `http://localhost:8080` and configure the callback URLs from `ONBOARDING_AND_CHANNEL_SETUP.md` §2 in the Meta app dashboard.
