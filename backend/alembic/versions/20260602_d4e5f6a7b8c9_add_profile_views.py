"""add profile_views to users

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('profile_views', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('users', 'profile_views')
