"""add_signup_attribution

Revision ID: f9708986d682
Revises: f5a6b7c8d9e0
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9708986d682'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('signup_referrer', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('signup_landing_path', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('signup_landing_querystring', sa.String(500), nullable=True))
    op.add_column('users', sa.Column('utm_source', sa.String(200), nullable=True))
    op.add_column('users', sa.Column('utm_medium', sa.String(200), nullable=True))
    op.add_column('users', sa.Column('utm_campaign', sa.String(200), nullable=True))
    op.add_column('users', sa.Column('utm_content', sa.String(200), nullable=True))
    op.add_column('users', sa.Column('utm_term', sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'utm_term')
    op.drop_column('users', 'utm_content')
    op.drop_column('users', 'utm_campaign')
    op.drop_column('users', 'utm_medium')
    op.drop_column('users', 'utm_source')
    op.drop_column('users', 'signup_landing_querystring')
    op.drop_column('users', 'signup_landing_path')
    op.drop_column('users', 'signup_referrer')
