"""Add session_contexts and session_files tables

Revision ID: 003_session_tables
Revises: 002_task_id_nullable
Create Date: 2026-03-28 120000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_session_tables'
down_revision: Union[str, None] = '002_task_id_nullable'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 session_contexts 表（会话上下文）
    # 检查表是否已存在，避免 SQLAlchemy create_all 后重复创建
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT tablename FROM pg_tables WHERE tablename = 'session_contexts'"))
    if not result.fetchone():
        op.create_table(
            'session_contexts',
            sa.Column('id', sa.Integer(), nullable=False, comment='主键ID'),
            sa.Column('session_id', sa.String(length=100), nullable=False, comment='会话ID'),
            sa.Column('context_key', sa.String(length=100), nullable=False, comment='上下文键'),
            sa.Column('context_value', postgresql.JSON(astext_type=sa.Text()), nullable=False, comment='上下文值'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='创建时间'),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='更新时间'),
            sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_session_contexts_session_key', 'session_contexts', ['session_id', 'context_key'], unique=True)
        op.create_index('ix_session_contexts_session_id', 'session_contexts', ['session_id'])

    # 2. 创建 session_files 表（会话文件）
    result = conn.execute(sa.text("SELECT tablename FROM pg_tables WHERE tablename = 'session_files'"))
    if not result.fetchone():
        op.create_table(
            'session_files',
            sa.Column('id', sa.Integer(), nullable=False, comment='主键ID'),
            sa.Column('session_id', sa.String(length=100), nullable=False, comment='会话ID'),
            sa.Column('file_path', sa.String(length=500), nullable=False, comment='文件路径'),
            sa.Column('absolute_path', sa.String(length=1000), nullable=True, comment='绝对路径'),
            sa.Column('file_type', sa.String(length=50), nullable=False, comment='文件类型'),
            sa.Column('size', sa.Integer(), nullable=False, server_default='0', comment='文件大小'),
            sa.Column('language', sa.String(length=50), nullable=True, comment='语言/技术栈'),
            sa.Column('is_entrypoint', sa.Boolean(), nullable=False, server_default='false', comment='是否主入口文件'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='创建时间'),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='更新时间'),
            sa.ForeignKeyConstraint(['session_id'], ['sessions.session_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_session_files_session', 'session_files', ['session_id', 'created_at'])
        op.create_index('ix_session_files_session_id', 'session_files', ['session_id'])

    # 3. 修改 sessions 表 - 添加 is_deleted 字段（如果不存在）
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = 'sessions' AND column_name = 'is_deleted'"))
    if not result.fetchone():
        op.add_column('sessions', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false', comment='软删除标记'))

    # 4. 迁移现有数据（如果有 meta_data 或 task_path，需要处理）

    # 5. 删除不再需要的列（可选，视需求而定）
    # 注意：保留 meta_data 和 task_path 以便数据迁移，之后可以删除
    # op.drop_column('sessions', 'meta_data')
    # op.drop_column('sessions', 'task_path')


def downgrade() -> None:
    op.drop_index('ix_session_files_session_id', table_name='session_files')
    op.drop_index('ix_session_files_session', table_name='session_files')
    op.drop_table('session_files')

    op.drop_index('ix_session_contexts_session_id', table_name='session_contexts')
    op.drop_index('ix_session_contexts_session_key', table_name='session_contexts')
    op.drop_table('session_contexts')

    op.drop_column('sessions', 'is_deleted')
