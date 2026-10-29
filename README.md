# SocialCommerce

Multi-tenant social-commerce SaaS for SMEs: WhatsApp and Facebook Messenger conversations → customers → orders → invoices → delivery and payment records → customer history and dashboards.

| Document | What it covers |
|---|---|
| [`social-media-management.md`](social-media-management.md) | Product specification (source of truth for requirements) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture and key decisions |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Database design and ERD |
| [`docs/ONBOARDING_AND_CHANNEL_SETUP.md`](docs/ONBOARDING_AND_CHANNEL_SETUP.md) | SME onboarding, Facebook and WhatsApp connection wizards |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Local setup, running services, tests, migrations |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Server installation, HTTPS, updates, rollback, operations |

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
- Phase 3 (Facebook Messenger): built and tested end to end on the test server (myleadtoday.cloud) — Messenger adapter, Connect Facebook Page wizard, channel health, deauthorize/data-deletion callbacks.
- Phase 4 (WhatsApp): built — Cloud API adapter, Embedded Signup wizard (new number or keep the WhatsApp Business app), resumable activation, quality and display-name tracking. Goes live with the Meta app values (see `docs/DEVELOPMENT.md`).
- Phase 5 (Sales): built — products with variants, prices and stock; orders from a chat, phone or walk-in with status flow and stock movement; tax invoices (bilingual PDF, numbered per fiscal year, locked once issued); file storage (S3 / SeaweedFS locally); orders on Customer 360.
- Phase 6 (Deliveries and payments): built — deliveries by own staff, courier or customer pickup with a status trail that moves the order along; cash on delivery recorded at the doorstep; payments and refunds (cash, eSewa, Khalti, Fonepay, bank, cheque) that are never edited, only voided with a reason; paid/due balances on orders and invoices; Deliveries and Payments pages, rider view on the phone.
- Phase 7 (Dashboard and reports): built — period picker (today to 90 days, business timezone); sales, money received, new orders and messages with change against the previous period; money still to collect, overdue invoices, orders in progress and deliveries due; sales chart (hourly/daily/weekly, with a table view); channel performance; chat-to-order funnel; sales by lead source; orders by status; new and returning buyers. Shown to roles with `report.read`.
- Next: Phase 8 (production hardening and MVP release).
