"""add_print_settings

Revision ID: b7c4d2e9f1a3
Revises: a2f3e8c1d4b7
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c4d2e9f1a3'
down_revision: Union[str, None] = 'a2f3e8c1d4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('prints', sa.Column('layer_height', sa.Float(), nullable=True))
    op.add_column('prints', sa.Column('infill_pct', sa.Integer(), nullable=True))
    op.add_column('prints', sa.Column('supports', sa.Boolean(), nullable=True))
    op.add_column('prints', sa.Column('print_time_mins', sa.Integer(), nullable=True))
    op.add_column('prints', sa.Column('filament_used_g', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('prints', 'filament_used_g')
    op.drop_column('prints', 'print_time_mins')
    op.drop_column('prints', 'supports')
    op.drop_column('prints', 'infill_pct')
    op.drop_column('prints', 'layer_height')
