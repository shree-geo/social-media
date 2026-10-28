#!/usr/bin/env bash
# Runs once, on first initialisation of the Postgres data volume.
# Creates the runtime roles described in docs/ARCHITECTURE.md §6:
#   app_owner    (POSTGRES_USER) owns the schema, used by migrations only
#   app_runtime  tenant API + workers, RLS enforced
#   app_platform platform admin + system jobs, bypasses RLS
# Database-level grants are in 02-database-grants.sql (also used for the test database).
set -euo pipefail

: "${APP_RUNTIME_DB_PASSWORD:?APP_RUNTIME_DB_PASSWORD is required}"
: "${APP_PLATFORM_DB_PASSWORD:?APP_PLATFORM_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v runtime_pw="$APP_RUNTIME_DB_PASSWORD" \
  -v platform_pw="$APP_PLATFORM_DB_PASSWORD" <<-'EOSQL'
	CREATE ROLE app_runtime  LOGIN PASSWORD :'runtime_pw'  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
	CREATE ROLE app_platform LOGIN PASSWORD :'platform_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
EOSQL
