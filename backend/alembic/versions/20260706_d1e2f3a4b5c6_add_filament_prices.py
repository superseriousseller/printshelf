"""add filament_prices (instruments pricing, Slice 3)

The one maintained pricing input, per the spec: material -> $/kg. Everything
else (spool/build/play cost) is computed at render time from this table plus
RegistryEntry.filament_usage/bom, never stored/cached.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'filament_prices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('material', sa.String(length=50), nullable=False),
        sa.Column('price_per_kg', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_filament_prices_material', 'filament_prices', ['material'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_filament_prices_material', 'filament_prices')
    op.drop_table('filament_prices')
