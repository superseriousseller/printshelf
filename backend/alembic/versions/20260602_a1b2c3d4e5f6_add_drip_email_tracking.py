"""add drip email tracking columns to users

Revision ID: a1b2c3d4e5f6
Revises: f4a7b2c9d1e5
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f4a7b2c9d1e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('drip_day2_sent', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('drip_day7_sent', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('users', 'drip_day7_sent')
    op.drop_column('users', 'drip_day2_sent')
