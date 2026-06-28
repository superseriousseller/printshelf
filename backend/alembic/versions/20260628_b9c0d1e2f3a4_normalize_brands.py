"""normalize existing filament + printer brand names

Folds known brand spellings (Bambu/BAMBULAB/Bambu Labs → Bambu Lab,
HATCHBOX → Hatchbox, etc.) to one canonical name so facet dropdowns and
Buy-link matching see a single spelling per brand. Uses the same
canonical_brand() the model validators use, so backfill == ongoing writes.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from models import canonical_brand
    bind = op.get_bind()
    for table in ("filaments", "printers"):
        rows = bind.execute(text(f"SELECT id, brand FROM {table}")).fetchall()
        for rid, brand in rows:
            canon = canonical_brand(brand)
            if canon != brand and canon is not None:
                bind.execute(
                    text(f"UPDATE {table} SET brand = :b WHERE id = :i"),
                    {"b": canon, "i": rid},
                )


def downgrade() -> None:
    # Data normalization — original spellings aren't recoverable. No-op.
    pass
