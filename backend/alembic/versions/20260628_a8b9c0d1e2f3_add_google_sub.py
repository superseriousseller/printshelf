"""add google_sub to users (OAuth login)

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('google_sub', sa.String(length=64), nullable=True))
    op.create_index('ix_users_google_sub', 'users', ['google_sub'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_google_sub', 'users')
    op.drop_column('users', 'google_sub')
