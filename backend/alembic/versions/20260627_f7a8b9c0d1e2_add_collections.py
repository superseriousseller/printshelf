"""add collections + collection_prints

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-06-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'collections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_collections_user_id', 'collections', ['user_id'])

    op.create_table(
        'collection_prints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collection_id', sa.Integer(), nullable=False),
        sa.Column('print_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['print_id'], ['prints.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_collection_prints_collection_id', 'collection_prints', ['collection_id'])
    op.create_index('ix_collection_prints_print_id', 'collection_prints', ['print_id'])
    op.create_index('ix_collection_prints_pair', 'collection_prints', ['collection_id', 'print_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_collection_prints_pair', 'collection_prints')
    op.drop_index('ix_collection_prints_print_id', 'collection_prints')
    op.drop_index('ix_collection_prints_collection_id', 'collection_prints')
    op.drop_table('collection_prints')
    op.drop_index('ix_collections_user_id', 'collections')
    op.drop_table('collections')
