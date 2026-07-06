"""add registry_entries (instruments collection, Slice 1)

Vertical-agnostic registry entry table. "instruments" is the first vertical
(flat `vertical` column, not a join table — one vertical exists today).
`bom`/`filament_usage`/`media` are JSON (matches the Print.filament_ids
precedent; no relational query need since this is fully curated, not
community-filterable). `owner_build_print_id` FKs to an existing Print row
rather than duplicating filament/date data.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'registry_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vertical', sa.String(length=30), nullable=False, server_default='instruments'),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('designer', sa.String(length=200), nullable=True),
        sa.Column('family', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='listed'),

        sa.Column('function_axis', sa.Integer(), nullable=True),
        sa.Column('fidelity_axis', sa.Integer(), nullable=True),
        sa.Column('objective_score', sa.Float(), nullable=True),
        sa.Column('effort_print_load', sa.String(length=10), nullable=True),
        sa.Column('effort_assembly_skill', sa.Integer(), nullable=True),
        sa.Column('verified_by_owner', sa.Boolean(), nullable=False, server_default=sa.false()),

        sa.Column('license', sa.String(length=200), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('demo_url', sa.String(length=1000), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),

        sa.Column('gap_why', sa.Text(), nullable=True),
        sa.Column('gap_status', sa.String(length=100), nullable=True),
        sa.Column('gap_closest', sa.Text(), nullable=True),

        sa.Column('retail_budget_price', sa.Float(), nullable=True),
        sa.Column('retail_budget_url', sa.String(length=1000), nullable=True),
        sa.Column('retail_budget_checked_at', sa.DateTime(), nullable=True),
        sa.Column('retail_premium_price', sa.Float(), nullable=True),
        sa.Column('retail_premium_url', sa.String(length=1000), nullable=True),
        sa.Column('retail_premium_checked_at', sa.DateTime(), nullable=True),

        sa.Column('filament_usage', sa.JSON(), nullable=True),
        sa.Column('bom', sa.JSON(), nullable=True),
        sa.Column('media', sa.JSON(), nullable=True),

        sa.Column('owner_build_print_id', sa.Integer(), nullable=True),
        sa.Column('owner_build_episode_url', sa.String(length=1000), nullable=True),

        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),

        sa.ForeignKeyConstraint(['owner_build_print_id'], ['prints.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_registry_entries_vertical_slug', 'registry_entries',
        ['vertical', 'slug'], unique=True,
    )
    op.create_index(
        'ix_registry_entries_vertical_status', 'registry_entries',
        ['vertical', 'status'],
    )
    op.create_index(
        'ix_registry_entries_owner_build_print_id', 'registry_entries',
        ['owner_build_print_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_registry_entries_owner_build_print_id', 'registry_entries')
    op.drop_index('ix_registry_entries_vertical_status', 'registry_entries')
    op.drop_index('ix_registry_entries_vertical_slug', 'registry_entries')
    op.drop_table('registry_entries')
