"""add index on likes.created_at for the trending window query

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_likes_created_at', 'likes', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_likes_created_at', 'likes')
