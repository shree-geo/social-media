"""product photo and website link

Products get an optional link to the business's own website page. Photos use the
existing ``product_images`` table; the app keeps one per product for now.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-30 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('products', sa.Column('website_url', sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f('products_website_url_check'), 'products', "website_url ~ '^https?://' AND length(website_url) <= 500"
    )


def downgrade() -> None:
    op.drop_constraint(op.f('products_website_url_check'), 'products', type_='check')
    op.drop_column('products', 'website_url')
