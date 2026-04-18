"""Fix tasks table updated_at default value

Revision ID: 006_fix_tasks_updated_at
Revises: 005_fix_tasks_created_at
Create Date: 2026-03-28 22:10:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '006_fix_tasks_updated_at'
down_revision: Union[str, None] = '005_fix_tasks_created_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 为 tasks 表的 updated_at 列添加默认值
    op.execute("""
        ALTER TABLE tasks
        ALTER COLUMN updated_at SET DEFAULT NOW()
    """)
    # 为现有空值设置默认值
    op.execute("""
        UPDATE tasks SET updated_at = NOW() WHERE updated_at IS NULL
    """)
    # 确保 NOT NULL 约束
    op.execute("""
        ALTER TABLE tasks ALTER COLUMN updated_at SET NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE tasks ALTER COLUMN updated_at DROP DEFAULT
    """)
