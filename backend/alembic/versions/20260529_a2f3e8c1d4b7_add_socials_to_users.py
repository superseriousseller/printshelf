"""add_socials_to_users

Revision ID: a2f3e8c1d4b7
Revises: cdf030b7af53
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2f3e8c1d4b7'
down_revision: Union[str, None] = 'cdf030b7af53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('socials', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'socials')
