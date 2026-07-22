"""add surface column to affiliate_clicks

Which page/CTA drove the click (print_detail_filament, print_detail_link,
dashboard_filament_buy, dashboard_catalog_buy, preview_public_buy) — needed
to see which surfaces actually generate clicks now that the print-detail
page's Buy CTAs are tracked too.

Revision ID: f5a6b7c8d9e0
Revises: e2f3a4b5c6d7
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('affiliate_clicks', sa.Column('surface', sa.String(length=40), nullable=True))
    op.create_index('ix_affiliate_clicks_surface', 'affiliate_clicks', ['surface'])


def downgrade() -> None:
    op.drop_index('ix_affiliate_clicks_surface', 'affiliate_clicks')
    op.drop_column('affiliate_clicks', 'surface')
