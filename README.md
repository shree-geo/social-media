# SocialCommerce

Multi-tenant social-commerce SaaS for SMEs: WhatsApp and Facebook Messenger conversations → customers → orders → invoices → delivery and payment records → customer history and dashboards.

| Document | What it covers |
|---|---|
| [`social-media-management.md`](social-media-management.md) | Product specification (source of truth for requirements) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture and key decisions |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Database design and ERD |
| [`docs/ONBOARDING_AND_CHANNEL_SETUP.md`](docs/ONBOARDING_AND_CHANNEL_SETUP.md) | SME onboarding, Facebook and WhatsApp connection wizards |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Local setup, running services, tests, migrations |

## Repository layout

```text
backend/     FastAPI API, Celery workers, Alembic migrations, tests
frontend/    Next.js (App Router, TypeScript, Tailwind)
infra/       nginx config, PostgreSQL init scripts (database roles)
docs/        architecture, database, onboarding and other documentation
docker-compose.yml        full local stack
docker-compose.dev.yml    hot reload + exposed ports for development
docker-compose.prod.yml   single-VPS production overrides
```

## Quick start

Prerequisites: Docker with Compose v2.24+.

```bash
cp .env.example .env
# Generate real secrets for JWT_SECRET and ENCRYPTION_KEYS (commands are in .env.example)

docker compose up --build
```

Then open:

| URL | What |
|---|---|
| http://localhost:8080 | web app |
| http://localhost:8080/api/docs | API docs (non-production only) |
| http://localhost:8080/health/ready | readiness (database + Redis) |

For hot reload, exposed database ports, local S3 storage and Mailpit, see [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Status

- Phase 1 (Foundation): done — tenants, auth, subscriptions, platform console, onboarding.
- Phase 2 (Customers + Inbox): done — webhook framework, identity resolution, duplicates/merge, unified inbox, replies, live updates.
- Phase 3 (Facebook Messenger): built — Messenger adapter, Connect Facebook Page wizard, channel health, deauthorize/data-deletion callbacks. Goes live once the Meta app values are configured (see `docs/DEVELOPMENT.md`).
- Next: Phase 4 (WhatsApp Embedded Signup).
