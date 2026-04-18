"""Fix tasks table id column type from String to AutoIncrement Integer

Revision ID: 004_fix_tasks_id
Revises: 003_session_tables
Create Date: 2026-03-28 220000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '004_fix_tasks_id'
down_revision: Union[str, None] = '003_session_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 为 tasks 表创建序列
    op.execute("CREATE SEQUENCE IF NOT EXISTS tasks_id_seq")

    # 2. 修改 id 列类型为 INTEGER 并设置默认值为 nextval
    op.execute("""
        ALTER TABLE tasks
        ALTER COLUMN id TYPE INTEGER USING id::integer,
        ALTER COLUMN id SET DEFAULT nextval('tasks_id_seq'::regclass),
        ALTER COLUMN id SET NOT NULL
    """)

    # 3. 为现有行的 id 设置序列的当前值
    # 使用 is_called=false 确保下一个值从 1 开始（如果没有数据）或 max_id+1（如果有数据）
    op.execute("""
        DO $$
        DECLARE
            max_id INTEGER;
        BEGIN
            SELECT MAX(id::integer) INTO max_id FROM tasks;
            IF max_id IS NULL THEN
                PERFORM setval('tasks_id_seq', 1, false);
            ELSE
                PERFORM setval('tasks_id_seq', max_id, true);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # 回滚：将 id 改回 String
    op.execute("""
        ALTER TABLE tasks
        ALTER COLUMN id TYPE VARCHAR(36) USING id::varchar,
        ALTER COLUMN id DROP DEFAULT,
        ALTER COLUMN id DROP NOT NULL
    """)
    op.execute("DROP SEQUENCE IF EXISTS tasks_id_seq")
