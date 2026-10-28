"""route_channel_business: account-level webhooks (WhatsApp quality / name / account updates)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # WhatsApp account-level events identify the WhatsApp Business Account, not a phone
    # number. Like route_channel_account, this returns only the owning tenant and connection.
    op.execute(
        """
        CREATE FUNCTION route_channel_business(p_provider text, p_business_id text)
        RETURNS TABLE (tenant_id uuid, connection_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT tenant_id, id FROM channel_connections
          WHERE provider = p_provider AND external_business_id = p_business_id
            AND status = 'connected'
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION route_channel_business(text, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION route_channel_business(text, text) TO app_runtime")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS route_channel_business(text, text)")
