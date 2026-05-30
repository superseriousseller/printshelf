"""add_email_verification

Revision ID: e3f6a9b2c8d5
Revises: d2e5f8a3b9c1
Create Date: 2026-05-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f6a9b2c8d5'
down_revision: Union[str, None] = 'd2e5f8a3b9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='0'))
    # Grandfather all existing users as verified so they aren't locked out
    op.execute("UPDATE users SET email_verified = 1 WHERE email_verified = 0")

    op.create_table(
        'email_verification_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('ix_email_verification_tokens_token', 'email_verification_tokens', ['token'])
    op.create_index('ix_email_verification_tokens_user_id', 'email_verification_tokens', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_email_verification_tokens_user_id', 'email_verification_tokens')
    op.drop_index('ix_email_verification_tokens_token', 'email_verification_tokens')
    op.drop_table('email_verification_tokens')
    op.drop_column('users', 'email_verified')
