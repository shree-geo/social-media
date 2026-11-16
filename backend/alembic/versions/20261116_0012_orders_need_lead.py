"""orders from chats go through a lead

Business setting: when on (the default, also for existing businesses), an order linked to a
WhatsApp or Messenger chat can only be created by converting a lead.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-16 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'tenant_settings', sa.Column('orders_need_lead', sa.Boolean(), server_default=sa.text('true'), nullable=False)
    )


def downgrade() -> None:
    op.drop_column('tenant_settings', 'orders_need_lead')
