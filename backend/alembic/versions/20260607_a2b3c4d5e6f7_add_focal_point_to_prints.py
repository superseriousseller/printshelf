"""add focal point to prints

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('prints', sa.Column('focal_x', sa.Float(), nullable=True))
    op.add_column('prints', sa.Column('focal_y', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('prints', 'focal_y')
    op.drop_column('prints', 'focal_x')
