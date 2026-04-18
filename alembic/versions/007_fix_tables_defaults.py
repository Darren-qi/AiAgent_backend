"""Fix id autoincrement and timestamp defaults for tasks and execution_nodes

Revision ID: 007_fix_tables_defaults
Revises: 006_fix_tasks_updated_at
Create Date: 2026-03-28 23:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '007_fix_tables_defaults'
down_revision: Union[str, None] = '006_fix_tasks_updated_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ========================================
    # 修复 tasks 表
    # ========================================

    # 1. 确保 id 列是 INTEGER 类型并有自增
    # 检查是否需要创建序列
    result = conn.execute(sa.text("SELECT sequence_name FROM information_schema.sequences WHERE sequence_name = 'tasks_id_seq'"))
    if not result.fetchone():
        op.execute("CREATE SEQUENCE tasks_id_seq START WITH 1")

    # 2. 获取当前 id 列的类型
    result = conn.execute(sa.text("SELECT data_type FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'id'"))
    row = result.fetchone()
    current_type = row[0] if row else None

    # 3. 如果 id 列类型不是 integer，则修改类型
    if current_type and current_type.lower() != 'integer':
        # 检查是否有非整数值
        result = conn.execute(sa.text("SELECT COUNT(*) FROM tasks WHERE id IS NOT NULL AND id::text ~ '[^0-9-]'"))
        has_non_numeric = result.fetchone()[0] > 0

        if not has_non_numeric:
            # 将 id 转为 INTEGER
            op.execute("ALTER TABLE tasks ALTER COLUMN id TYPE INTEGER USING id::integer")
        else:
            # 创建一个临时整数列并复制数据
            op.execute("ALTER TABLE tasks ADD COLUMN id_new INTEGER")
            op.execute("UPDATE tasks SET id_new = CAST(id AS INTEGER) WHERE id IS NOT NULL")
            op.execute("ALTER TABLE tasks DROP COLUMN id")
            op.execute("ALTER TABLE tasks RENAME COLUMN id_new TO id")

    # 4. 设置 id 列的默认值和 NOT NULL
    op.execute("""
        ALTER TABLE tasks
        ALTER COLUMN id SET DEFAULT nextval('tasks_id_seq'::regclass),
        ALTER COLUMN id SET NOT NULL
    """)

    # 5. 为现有行的 id 设置序列值
    op.execute("""
        DO $$
        DECLARE
            max_id INTEGER;
        BEGIN
            SELECT MAX(id) INTO max_id FROM tasks WHERE id IS NOT NULL;
            IF max_id IS NULL THEN
                PERFORM setval('tasks_id_seq', 1, false);
            ELSE
                PERFORM setval('tasks_id_seq', max_id + 1, false);
            END IF;
        END $$;
    """)

    # 6. 设置 created_at 默认值
    op.execute("ALTER TABLE tasks ALTER COLUMN created_at SET DEFAULT NOW()")
    op.execute("UPDATE tasks SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("ALTER TABLE tasks ALTER COLUMN created_at SET NOT NULL")

    # 7. 设置 updated_at 默认值
    op.execute("ALTER TABLE tasks ALTER COLUMN updated_at SET DEFAULT NOW()")
    op.execute("UPDATE tasks SET updated_at = NOW() WHERE updated_at IS NULL")
    op.execute("ALTER TABLE tasks ALTER COLUMN updated_at SET NOT NULL")

    # ========================================
    # 修复 execution_nodes 表
    # ========================================

    # 1. 检查是否需要创建序列
    result = conn.execute(sa.text("SELECT sequence_name FROM information_schema.sequences WHERE sequence_name = 'execution_nodes_id_seq'"))
    if not result.fetchone():
        op.execute("CREATE SEQUENCE execution_nodes_id_seq START WITH 1")

    # 2. 获取当前 id 列的类型
    result = conn.execute(sa.text("SELECT data_type FROM information_schema.columns WHERE table_name = 'execution_nodes' AND column_name = 'id'"))
    row = result.fetchone()
    current_type = row[0] if row else None

    # 3. 如果 id 列类型不是 integer，则修改类型
    if current_type and current_type.lower() != 'integer':
        result = conn.execute(sa.text("SELECT COUNT(*) FROM execution_nodes WHERE id IS NOT NULL AND id::text ~ '[^0-9-]'"))
        has_non_numeric = result.fetchone()[0] > 0

        if not has_non_numeric:
            op.execute("ALTER TABLE execution_nodes ALTER COLUMN id TYPE INTEGER USING id::integer")
        else:
            op.execute("ALTER TABLE execution_nodes ADD COLUMN id_new INTEGER")
            op.execute("UPDATE execution_nodes SET id_new = CAST(id AS INTEGER) WHERE id IS NOT NULL")
            op.execute("ALTER TABLE execution_nodes DROP COLUMN id")
            op.execute("ALTER TABLE execution_nodes RENAME COLUMN id_new TO id")

    # 4. 设置 id 列的默认值和 NOT NULL
    op.execute("""
        ALTER TABLE execution_nodes
        ALTER COLUMN id SET DEFAULT nextval('execution_nodes_id_seq'::regclass),
        ALTER COLUMN id SET NOT NULL
    """)

    # 5. 为现有行的 id 设置序列值
    op.execute("""
        DO $$
        DECLARE
            max_id INTEGER;
        BEGIN
            SELECT MAX(id) INTO max_id FROM execution_nodes WHERE id IS NOT NULL;
            IF max_id IS NULL THEN
                PERFORM setval('execution_nodes_id_seq', 1, false);
            ELSE
                PERFORM setval('execution_nodes_id_seq', max_id + 1, false);
            END IF;
        END $$;
    """)

    # 6. 设置 created_at 默认值
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN created_at SET DEFAULT NOW()")
    op.execute("UPDATE execution_nodes SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN created_at SET NOT NULL")

    # 7. 设置 updated_at 默认值
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN updated_at SET DEFAULT NOW()")
    op.execute("UPDATE execution_nodes SET updated_at = NOW() WHERE updated_at IS NULL")
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN updated_at SET NOT NULL")

    # ========================================
    # 修复 sessions 表
    # ========================================
    op.execute("ALTER TABLE sessions ALTER COLUMN created_at SET DEFAULT NOW()")
    op.execute("UPDATE sessions SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("ALTER TABLE sessions ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE sessions ALTER COLUMN updated_at SET DEFAULT NOW()")
    op.execute("UPDATE sessions SET updated_at = NOW() WHERE updated_at IS NULL")
    op.execute("ALTER TABLE sessions ALTER COLUMN updated_at SET NOT NULL")

    # ========================================
    # 修复 users 表
    # ========================================
    op.execute("ALTER TABLE users ALTER COLUMN created_at SET DEFAULT NOW()")
    op.execute("UPDATE users SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at SET DEFAULT NOW()")
    op.execute("UPDATE users SET updated_at = NOW() WHERE updated_at IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at SET NOT NULL")

    # ========================================
    # 修复 experiences 表
    # ========================================
    op.execute("ALTER TABLE experiences ALTER COLUMN created_at SET DEFAULT NOW()")
    op.execute("UPDATE experiences SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("ALTER TABLE experiences ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE experiences ALTER COLUMN updated_at SET DEFAULT NOW()")
    op.execute("UPDATE experiences SET updated_at = NOW() WHERE updated_at IS NULL")
    op.execute("ALTER TABLE experiences ALTER COLUMN updated_at SET NOT NULL")


def downgrade() -> None:
    # 回滚 tasks 表
    op.execute("ALTER TABLE tasks ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE tasks ALTER COLUMN id DROP NOT NULL")
    op.execute("ALTER TABLE tasks ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE tasks ALTER COLUMN created_at DROP NOT NULL")
    op.execute("ALTER TABLE tasks ALTER COLUMN updated_at DROP DEFAULT")
    op.execute("ALTER TABLE tasks ALTER COLUMN updated_at DROP NOT NULL")
    op.execute("DROP SEQUENCE IF EXISTS tasks_id_seq")

    # 回滚 execution_nodes 表
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN id DROP NOT NULL")
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN created_at DROP NOT NULL")
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN updated_at DROP DEFAULT")
    op.execute("ALTER TABLE execution_nodes ALTER COLUMN updated_at DROP NOT NULL")
    op.execute("DROP SEQUENCE IF EXISTS execution_nodes_id_seq")

    # 回滚 sessions 表
    op.execute("ALTER TABLE sessions ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE sessions ALTER COLUMN created_at DROP NOT NULL")
    op.execute("ALTER TABLE sessions ALTER COLUMN updated_at DROP DEFAULT")
    op.execute("ALTER TABLE sessions ALTER COLUMN updated_at DROP NOT NULL")

    # 回滚 users 表
    op.execute("ALTER TABLE users ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN created_at DROP NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at DROP NOT NULL")

    # 回滚 experiences 表
    op.execute("ALTER TABLE experiences ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE experiences ALTER COLUMN created_at DROP NOT NULL")
    op.execute("ALTER TABLE experiences ALTER COLUMN updated_at DROP DEFAULT")
    op.execute("ALTER TABLE experiences ALTER COLUMN updated_at DROP NOT NULL")
