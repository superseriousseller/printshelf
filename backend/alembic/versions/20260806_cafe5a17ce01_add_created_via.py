"""add_created_via source attribution

Adds `created_via` (which client created the row) to printers, filaments, prints.
Existing rows get server_default 'unknown'; a separate best-effort backfill
(backend/scripts/backfill_created_via.py) can refine them.

Revision ID: cafe5a17ce01
Revises: d92cf42b4c26
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cafe5a17ce01'
down_revision: Union[str, None] = 'd92cf42b4c26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("printers", "filaments", "prints")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "created_via",
                sa.String(20),
                nullable=False,
                server_default="unknown",
            ),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "created_via")
