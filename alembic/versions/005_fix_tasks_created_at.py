"""Fix tasks table created_at default value

Revision ID: 005_fix_tasks_created_at
Revises: 004_fix_tasks_id
Create Date: 2026-03-28 22:05:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '005_fix_tasks_created_at'
down_revision: Union[str, None] = '004_fix_tasks_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 为 tasks 表的 created_at 列添加默认值（如果还没有的话）
    op.execute("""
        ALTER TABLE tasks
        ALTER COLUMN created_at SET DEFAULT NOW()
    """)
    # 为现有空值设置默认值
    op.execute("""
        UPDATE tasks SET created_at = NOW() WHERE created_at IS NULL
    """)
    # 确保 NOT NULL 约束
    op.execute("""
        ALTER TABLE tasks ALTER COLUMN created_at SET NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE tasks ALTER COLUMN created_at DROP DEFAULT
    """)
