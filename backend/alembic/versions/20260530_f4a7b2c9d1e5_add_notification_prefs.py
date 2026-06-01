"""add_notification_prefs

Revision ID: f4a7b2c9d1e5
Revises: e3f6a9b2c8d5
Create Date: 2026-05-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a7b2c9d1e5'
down_revision: Union[str, None] = 'e3f6a9b2c8d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('notify_follow', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('users', sa.Column('notify_feed', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('users', sa.Column('unsubscribe_token', sa.String(32), nullable=True))
    # Backfill unsubscribe tokens — dialect-aware (SQLite lacks md5/::text)
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("UPDATE users SET unsubscribe_token = md5(random()::text || id::text) WHERE unsubscribe_token IS NULL")
    else:
        op.execute("UPDATE users SET unsubscribe_token = lower(hex(randomblob(16))) WHERE unsubscribe_token IS NULL")


def downgrade() -> None:
    op.drop_column('users', 'unsubscribe_token')
    op.drop_column('users', 'notify_feed')
    op.drop_column('users', 'notify_follow')
