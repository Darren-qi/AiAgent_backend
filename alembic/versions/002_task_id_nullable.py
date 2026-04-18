"""make task_id nullable

Revision ID: 002_task_id_nullable
Revises: 001
Create Date: 2026-03-26 222237

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '002_task_id_nullable'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('execution_nodes', 'task_id',
               existing_type=sa.VARCHAR(length=100),
               nullable=True,
               existing_comment='任务ID')


def downgrade() -> None:
    op.alter_column('execution_nodes', 'task_id',
               existing_type=sa.VARCHAR(length=100),
               nullable=False,
               existing_comment='任务ID')
