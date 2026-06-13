"""add color_hex_source to filaments

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('filaments', sa.Column('color_hex_source', sa.String(10), nullable=True))


def downgrade():
    op.drop_column('filaments', 'color_hex_source')
