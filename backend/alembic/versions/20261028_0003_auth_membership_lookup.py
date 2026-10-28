"""auth: membership lookup for login (pre-tenant context)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Login and refresh run before a tenant is chosen, so RLS hides memberships from
    # app_runtime. This function exposes only one user's active memberships (and whether
    # each is an OWNER), instead of giving the auth path the RLS-bypassing role.
    op.execute(
        """
        CREATE FUNCTION auth_user_memberships(p_user_id uuid)
        RETURNS TABLE (tenant_id uuid, membership_id uuid, business_name text, is_owner boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT m.tenant_id, m.id, t.business_name,
                 EXISTS (
                   SELECT 1 FROM membership_roles mr JOIN roles r ON r.id = mr.role_id
                   WHERE mr.membership_id = m.id AND r.code = 'OWNER'
                 )
          FROM tenant_memberships m
          JOIN tenants t ON t.id = m.tenant_id
          WHERE m.user_id = p_user_id AND m.status = 'active'
            AND t.status = 'active' AND t.deleted_at IS NULL
          ORDER BY m.joined_at NULLS LAST, m.created_at
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_user_memberships(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_user_memberships(uuid) TO app_runtime")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_user_memberships(uuid)")
