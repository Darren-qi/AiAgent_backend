"""写操作意图日志表 action_journal

崩溃安全的写操作 WAL：执行前落 intent，执行后回写结果；
崩溃残留 running 行用于重试时裁决「已生效/未生效/无法确认」。

Revision ID: 010
Revises: 009
Create Date: 2026-11-18
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_journal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=True),
        sa.Column("todo_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("op_key", sa.String(length=64), nullable=False),
        sa.Column("semantics", sa.String(length=16), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("op_key", name="uq_action_journal_op_key"),
        comment="写操作意图日志",
    )
    op.create_index("ix_action_journal_session_id", "action_journal", ["session_id"])
    op.create_index("ix_action_journal_task_id", "action_journal", ["task_id"])
    op.create_index("ix_action_journal_status", "action_journal", ["status"])
    op.create_index(
        "ix_action_journal_session_status", "action_journal", ["session_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_action_journal_session_status", table_name="action_journal")
    op.drop_index("ix_action_journal_status", table_name="action_journal")
    op.drop_index("ix_action_journal_task_id", table_name="action_journal")
    op.drop_index("ix_action_journal_session_id", table_name="action_journal")
    op.drop_table("action_journal")
