"""add video_url to prints

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('prints', sa.Column('video_url', sa.String(1000), nullable=True))


def downgrade():
    op.drop_column('prints', 'video_url')
