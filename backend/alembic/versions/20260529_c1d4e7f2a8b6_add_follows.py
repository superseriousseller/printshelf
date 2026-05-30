"""add_follows

Revision ID: c1d4e7f2a8b6
Revises: b7c4d2e9f1a3
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d4e7f2a8b6'
down_revision: Union[str, None] = 'b7c4d2e9f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'follows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('follower_id', sa.Integer(), nullable=False),
        sa.Column('following_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['follower_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['following_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('follower_id', 'following_id', name='uq_follows_pair'),
    )
    op.create_index('ix_follows_follower_id', 'follows', ['follower_id'])
    op.create_index('ix_follows_following_id', 'follows', ['following_id'])


def downgrade() -> None:
    op.drop_index('ix_follows_following_id', 'follows')
    op.drop_index('ix_follows_follower_id', 'follows')
    op.drop_table('follows')
