"""add likes table and engagement counters to prints

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'likes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('print_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['print_id'], ['prints.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_likes_user_id', 'likes', ['user_id'])
    op.create_index('ix_likes_print_id', 'likes', ['print_id'])
    op.create_index('ix_likes_pair', 'likes', ['user_id', 'print_id'], unique=True)

    op.add_column('prints', sa.Column('like_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('prints', sa.Column('view_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('prints', 'view_count')
    op.drop_column('prints', 'like_count')
    op.drop_index('ix_likes_pair', 'likes')
    op.drop_index('ix_likes_print_id', 'likes')
    op.drop_index('ix_likes_user_id', 'likes')
    op.drop_table('likes')
