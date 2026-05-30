"""add_affiliate_clicks

Revision ID: d2e5f8a3b9c1
Revises: c1d4e7f2a8b6
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2e5f8a3b9c1'
down_revision: Union[str, None] = 'c1d4e7f2a8b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'affiliate_clicks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('filament_id', sa.Integer(), nullable=True),
        sa.Column('store', sa.String(50), nullable=True),
        sa.Column('clicked_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_affiliate_clicks_user_id', 'affiliate_clicks', ['user_id'])
    op.create_index('ix_affiliate_clicks_store', 'affiliate_clicks', ['store'])
    op.create_index('ix_affiliate_clicks_clicked_at', 'affiliate_clicks', ['clicked_at'])


def downgrade() -> None:
    op.drop_index('ix_affiliate_clicks_clicked_at', 'affiliate_clicks')
    op.drop_index('ix_affiliate_clicks_store', 'affiliate_clicks')
    op.drop_index('ix_affiliate_clicks_user_id', 'affiliate_clicks')
    op.drop_table('affiliate_clicks')
