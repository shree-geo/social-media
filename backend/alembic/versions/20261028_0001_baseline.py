"""baseline: extensions and RLS helper

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # Tenant id of the current transaction (set via set_config('app.tenant_id', ..., true)).
    # Returns NULL when unset, so RLS policies comparing against it match no rows.
    op.execute(
        """
        CREATE FUNCTION app_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE AS $$
          SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app_current_tenant() TO app_runtime, app_platform")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant()")
