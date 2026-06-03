"""add spool_weight_g to filaments

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('filaments', sa.Column('spool_weight_g', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('filaments', 'spool_weight_g')
