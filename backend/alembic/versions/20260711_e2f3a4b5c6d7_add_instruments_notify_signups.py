"""add instruments_notify_signups (Instruments Index notify-me slice)

Email capture for "let me know when new entries/verified builds land" — no
other columns yet (no source/consent tracking needed for a single-page
single-purpose list).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'instruments_notify_signups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_instruments_notify_signups_email', 'instruments_notify_signups', ['email'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_instruments_notify_signups_email', 'instruments_notify_signups')
    op.drop_table('instruments_notify_signups')
