# Deployment

How to run MyLeadToday on a single Linux server with Docker, and how to update it. This is how the test
server at https://myleadtoday.cloud runs. Local development is in [`DEVELOPMENT.md`](DEVELOPMENT.md).

## 1. What runs where

```
Internet ──HTTPS──▶ host nginx (TLS, certbot) ──▶ 127.0.0.1:8040 ──▶ nginx container ─┬─▶ frontend (Next.js)
                                                                                      └─▶ backend (FastAPI)
                    backend / worker / beat ──▶ postgres, redis, storage (SeaweedFS), mailpit   (Docker network only)
```

| Compose file | Purpose |
|---|---|
| `docker-compose.yml` | the services |
| `docker-compose.prod.yml` | production settings: `APP_ENV=production`, secure cookies, log rotation, nginx on port 80 |
| `docker-compose.server.yml` | a server **shared with other apps**: nginx on `127.0.0.1:8040` behind the host's nginx, bundled storage and mail kept |

On a dedicated server with nothing else on ports 80/443, use the first two files and terminate TLS in
front of it. On a shared server (like the test server), use all three; every command below assumes:

```bash
F="-f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.server.yml"
```

Database, Redis, storage and mail are never published outside the Docker network.

## 2. Server requirements

- Ubuntu 24.04 (or similar), 2 CPU / 4 GB RAM minimum for one installation, 20 GB free disk.
- Docker Engine with the Compose plugin, git, nginx, certbot.
- A DNS **A record** for the domain pointing at the server.
- SSH access with a key; the server can pull the repository (`git@github.com:shree-geo/social-media.git`).

## 3. First installation

### 3.1 Code and secrets

```bash
cd /var/www && git clone git@github.com:shree-geo/social-media.git && cd social-media
cp .env.example .env && chmod 600 .env
```

Edit `.env` (never commit it, never copy it off the server):

| Variable | Value |
|---|---|
| `APP_ENV` | `production` |
| `APP_NAME` | `MyLeadToday` |
| `APP_BASE_URL`, `CORS_ORIGINS` | `https://<domain>` |
| `COOKIE_SECURE` | `true` |
| `POSTGRES_PASSWORD`, `APP_RUNTIME_DB_PASSWORD`, `APP_PLATFORM_DB_PASSWORD` | three different random values (`openssl rand -hex 24`); put the same values into the three `DATABASE_*_URL`s |
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENCRYPTION_KEYS` | `python3 -c "import os,base64; print('v1:' + base64.b64encode(os.urandom(32)).decode())"` — **losing it makes stored Facebook/WhatsApp tokens unreadable** |
| `S3_SECRET_KEY` | random; `S3_ACCESS_KEY=app` |
| `META_*` | from the Meta app ([`ONBOARDING_AND_CHANNEL_SETUP.md`](ONBOARDING_AND_CHANNEL_SETUP.md) §2); `META_WEBHOOK_VERIFY_TOKEN` = `openssl rand -hex 32` |
| `SMTP_*`, `EMAIL_FROM` | a real mail provider, or leave on `mailpit` (mail is captured, not sent) |
| `BOOTSTRAP_ADMIN_EMAIL` | the first platform super admin |

The database role passwords are applied only when the database volume is first created; changing them
later needs `ALTER ROLE` as well.

### 3.2 Build and start

```bash
COMPOSE_PARALLEL_LIMIT=1 docker compose $F build     # one image at a time on small servers
docker compose $F up -d                               # `migrate` runs first: migrations + seed
umask 077; docker compose $F logs migrate --no-log-prefix > /root/socialcommerce-admin.txt
curl -s http://127.0.0.1:8040/health/ready            # {"status":"ok",...}
```

The `migrate` output contains the platform admin's **temporary password** (valid 7 days, must be
changed at first login). Keep that file root-only and delete it after the first login.

### 3.3 HTTPS and the host nginx

1. Copy the site file and adapt the domain: `infra/nginx/myleadtoday.conf` → `/etc/nginx/sites-available/<name>`,
   link it into `sites-enabled`.
2. `if nginx -t; then systemctl reload nginx; fi` — never reload when the test fails.
3. Certificate (webroot, renewed by `certbot.timer`):
   ```bash
   certbot certonly --webroot -w /var/www/certbot -d <domain> --deploy-hook "systemctl reload nginx"
   ```
4. Check `https://<domain>/health/ready` and `https://<domain>/login`.

### 3.4 After the first start

- Log in at `/admin/login`, change the password, then in **Settings** enter the support phone and email.
- Create **Packages**, then **Add a business**.
- Configure the Meta app and webhooks ([`ONBOARDING_AND_CHANNEL_SETUP.md`](ONBOARDING_AND_CHANNEL_SETUP.md)).

## 4. Updating

```bash
cd /var/www/social-media
docker compose $F exec -T postgres sh -c 'pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB' \
  > /root/socialcommerce-predeploy/$(date +%Y%m%d%H%M).dump      # before any release with migrations (umask 077)
git pull --ff-only
COMPOSE_PARALLEL_LIMIT=1 docker compose $F build
docker compose $F up -d                                            # migrate runs before backend starts
curl -s https://<domain>/health/ready
```

- Frontend-only change: `docker compose $F build frontend && docker compose $F up -d frontend`.
- Backend code is in the `migrate`/`backend`/`worker`/`beat` image (`socialcommerce-backend`); build it
  with a plain `build` (or `build migrate`) so every service gets the new code.
- Expect about 20–30 seconds of 502s while the backend restarts. The nginx container re-resolves
  container addresses, so no nginx restart is needed.
- A build can fail on a busy small server; check the output for `failed to solve` and re-run.

## 5. Rolling back

```bash
git log --oneline -5
git checkout <previous-commit> && COMPOSE_PARALLEL_LIMIT=1 docker compose $F build && docker compose $F up -d
```

Migrations are forward-only in production. If the bad release changed the database, restore the
pre-deploy dump taken in §4 into a fresh database before starting the old code, rather than running
Alembic downgrades on live data.

## 6. Day-to-day operations

| Task | Command |
|---|---|
| Status | `docker compose $F ps` |
| Logs | `docker compose $F logs -f --tail 100 backend worker` |
| Health | `curl -s https://<domain>/health/ready` |
| Database shell | `docker compose $F exec postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB'` |
| Migration version | `docker compose $F exec -T backend alembic current` |
| Restart one service | `docker compose $F restart worker` |

Logs are JSON, rotated at 20 MB × 5 files per container (`docker-compose.prod.yml`). Access tokens and
passwords are never logged.

## 7. Shared server rules

The test server also runs Grihastay, ymac and dfims. Never stop or reconfigure their containers, never
edit their nginx sites, and after every change check that they still answer. Keep this project's
containers, volumes and images under the `socialcommerce` Compose project name.
