"""add_email_optout_and_reengagement

Revision ID: d92cf42b4c26
Revises: f9708986d682
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd92cf42b4c26'
down_revision: Union[str, None] = 'f9708986d682'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # General marketing opt-out (separate from notify_follow/notify_feed, which
    # are per-notification-type). Reuses the existing unsubscribe_token via a
    # new /unsubscribe?type=marketing branch -- no new token column needed.
    op.add_column('users', sa.Column('email_opt_out', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    # Idempotency + audit trail for the one-time re-engagement campaign. A
    # timestamp (not just a bool) so we know when, matching created_at/last_login.
    op.add_column('users', sa.Column('reengagement_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'reengagement_sent_at')
    op.drop_column('users', 'email_opt_out')
