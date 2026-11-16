"""Add users.deepseek_api_key (user-level DeepSeek key, 2026-11-14)

Revision ID: 009
Revises: 008_add_user_fields
Create Date: 2026-11-14 16:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('deepseek_api_key', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'deepseek_api_key')
