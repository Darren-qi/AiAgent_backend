"""
经验模型模块
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, IDMixin, TimestampMixin


class ExperienceModel(Base, IDMixin, TimestampMixin):
    """
    经验模型

    存储成功的任务执行经验，供后续任务参考。
    """

    __tablename__ = "experiences"

    # 任务描述
    task: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
        comment="任务描述",
    )

    # 任务类型
    task_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="任务类型",
    )

    # 任务描述（用于检索）
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="详细描述",
    )

    # 解决方案
    solution: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="解决方案",
    )

    # 执行步骤 (JSON)
    steps: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="执行步骤",
    )

    # 是否成功
    success: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否成功",
    )

    # 成功次数
    success_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="成功次数",
    )

    # 失败次数
    failure_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="失败次数",
    )

    # 额外元数据 (JSON)
    meta_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="元数据",
    )

    # 用户 ID (可选)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="用户ID",
    )


class SessionModel(Base, IDMixin, TimestampMixin):
    """
    会话模型

    存储 Agent 会话信息。
    """

    __tablename__ = "sessions"

    # 会话唯一标识
    session_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="会话ID",
    )

    # 用户 ID
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )

    # 会话标题
    title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="会话标题",
    )

    # 会话状态
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
        comment="会话状态",
    )

    # 元数据 (JSON)
    meta_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="元数据",
    )


class TaskModel(Base, IDMixin, TimestampMixin):
    """
    任务模型

    存储 Agent 任务执行记录。
    """

    __tablename__ = "tasks"

    # 任务唯一标识
    task_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="任务ID",
    )

    # 会话 ID
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话ID",
    )

    # 用户 ID
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )

    # 任务描述
    task: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="任务描述",
    )

    # 任务类型
    task_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="任务类型",
    )

    # 任务状态
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        comment="任务状态",
    )

    # 执行结果
    result: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="执行结果",
    )

    # 错误信息
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息",
    )

    # 执行时间 (秒)
    execution_time: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="执行时间",
    )

    # 消耗成本
    cost: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        comment="消耗成本",
    )

    # 使用模型
    model: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="使用的模型",
    )

    # 元数据 (JSON)
    meta_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="元数据",
    )
