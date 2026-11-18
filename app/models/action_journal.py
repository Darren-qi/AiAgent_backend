"""
写操作意图日志模型 (action_journal)

崩溃安全的写操作 WAL（write-ahead log）：
执行前先落一行 intent，执行后回写结果。进程崩溃时残留 status='running'，
下一轮重入据此裁决「已生效 / 未生效 / 无法确认」，避免重试重复执行副作用
（重复扣款、重复发消息、重复执行命令等不可逆操作）。

设计要点：
    - op_key: sha256(session/task/action/params) —— 唯一索引，同一调用只有一行
    - status: running(执行中) / done(已成功) / failed(已失败，可安全重放) / ambiguous(已判定无法确认)
    - 不加外键：这是崩溃日志，必须在任何情况下都写得进去
    - 生命周期：任务成功 clear_state 时按 session 清理；否则按时间定期清理

语义三值由 SKILL.md frontmatter `op_semantics` 声明，未声明一律按"不可重放"处理。
"""

from typing import Any, Dict, Optional

from sqlalchemy import Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IDMixin, TimestampMixin


class ActionJournal(Base, IDMixin, TimestampMixin):
    """写操作意图日志表 (action_journal)"""

    __tablename__ = "action_journal"

    # 会话 ID（无外键：崩溃日志必须永远写得进去）
    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="会话ID",
    )

    # 任务 ID（可空：调用方可能没有 task 上下文）
    task_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        comment="任务ID",
    )

    # 待办 ID（字符串，与 todos[].id 一致；可空）
    todo_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="待办ID",
    )

    # 技能名（file_operations / sandbox / http_client ...）
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="技能名",
    )

    # 意图键：sha256(session|task|action|归一化参数)
    op_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="意图键（幂等去重）",
    )

    # 语义：idempotent(不记) / conditional(核验) / once(不可重放)
    semantics: Mapped[str] = mapped_column(
        String(16),
        default="once",
        nullable=False,
        comment="操作语义",
    )

    # 原始参数（审计 + 复现）
    params: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="原始参数",
    )

    # running / done / failed / ambiguous
    status: Mapped[str] = mapped_column(
        String(16),
        default="running",
        nullable=False,
        index=True,
        comment="状态",
    )

    # 成功时的结果快照（重放时直接返回）
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="结果快照",
    )

    # 失败原因
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息",
    )

    __table_args__ = (
        UniqueConstraint("op_key", name="uq_action_journal_op_key"),
        Index("ix_action_journal_session_status", "session_id", "status"),
        {"comment": "写操作意图日志"},
    )
