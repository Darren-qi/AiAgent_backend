"""
经验模型模块

存储 Agent 执行经验相关的数据：
- experiences: 成功的任务执行经验库
- sessions: Agent 会话信息
- tasks: 任务执行记录
- session_contexts: 会话上下文数据
- session_files: 会话生成的文件记录

数据库表:
    - experiences: 经验库 (成功案例)
    - sessions: 会话表
    - tasks: 任务表
    - session_contexts: 会话上下文表
    - session_files: 会话文件表
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Index
from app.db.base import Base, IDMixin, TimestampMixin


class ExperienceModel(Base, IDMixin, TimestampMixin):
    """
    经验模型表 (experiences)

    存储成功的任务执行经验，供后续相似任务参考。
    是 Agent 的"经验库"，支持经验驱动的执行优化。

    主要字段:
        - task: 任务描述 (用于检索)
        - task_type: 任务类型 (crawler/code/general 等)
        - description: 详细描述
        - solution: 解决方案
        - steps: 执行步骤 (JSON 数组)
        - success/failure_count: 成功/失败次数

    使用场景:
        - 任务规划时检索相似经验
        - 优化执行策略
        - 学习最佳实践

    检索方式:
        - 向量相似度检索 (pgvector)
        - BM25 关键词检索
        - 混合检索 (向量 + BM25)
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
    会话模型表 (sessions)

    存储 Agent 会话的基本信息。
    会话的上下文数据存储在 SessionContext 表中。

    主要字段:
        - session_id: 会话唯一标识 (UUID)
        - user_id: 所属用户ID
        - title: 会话标题
        - status: 会话状态 (active/completed/cancelled)
        - is_deleted: 软删除标记

    使用场景:
        - 会话列表展示
        - 会话历史查询
        - 会话统计

    注意:
        - 纯结构化存储，不存储实际对话内容
        - 对话内容存储在 conversation_messages 表
        - 上下文数据存储在 session_contexts 表
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
        comment="会话状态: active/completed/cancelled",
    )

    # 是否已删除
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="软删除标记",
    )


class TaskModel(Base, IDMixin, TimestampMixin):
    """
    任务模型表 (tasks)

    存储 Agent 任务执行记录。
    记录每个任务的执行状态、结果和成本统计。

    主要字段:
        - task_id: 任务唯一标识 (UUID)
        - session_id: 所属会话ID
        - user_id: 用户ID
        - task: 任务描述
        - task_type: 任务类型
        - status: 任务状态 (pending/running/completed/failed)
        - result: 执行结果
        - error: 错误信息
        - execution_time: 执行时间 (秒)
        - cost: 消耗成本
        - model: 使用的模型

    使用场景:
        - 任务执行追踪
        - 成本统计
        - 性能分析
        - 错误排查

    生命周期:
        1. pending: 任务已创建，等待执行
        2. running: 任务执行中
        3. completed: 任务成功完成
        4. failed: 任务执行失败
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


class SessionContext(Base, IDMixin, TimestampMixin):
    """
    会话上下文表 (session_contexts)

    存储会话的灵活上下文数据 (key-value 结构)。
    用于存储任务路径、模型选择、成本统计、最终结果等。

    主要字段:
        - session_id: 所属会话ID
        - context_key: 上下文键
        - context_value: 上下文值 (JSON)

    常用 context_key 值:
        - task_path: 当前任务路径
        - model: 使用的模型
        - total_cost: 累计成本
        - final_result: 最终结果
        - error: 错误信息
        - scratchpad: 思考过程草稿

    使用场景:
        - 任务中断后恢复执行
        - 跨步骤传递上下文
        - 会话状态持久化

    特点:
        - 灵活的 key-value 结构
        - JSON 类型支持任意数据结构
        - 自动 upsert 更新
    """

    __tablename__ = "session_contexts"

    # 会话 ID
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话ID",
    )

    # 上下文键
    context_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="上下文键: task_path/model/total_cost/final_result/error/scratchpad",
    )

    # 上下文值 (JSONB - 支持任意结构)
    context_value: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="上下文值",
    )

    __table_args__ = (
        Index("ix_session_contexts_session_key", "session_id", "context_key", unique=True),
        {"comment": "会话上下文表"},
    )


class SessionFile(Base, IDMixin, TimestampMixin):
    """
    会话文件表 (session_files)

    存储会话生成的文件及其元数据。
    记录 Agent 在任务执行过程中创建的所有文件。

    主要字段:
        - session_id: 所属会话ID
        - file_path: 文件路径 (相对于 tasks 目录)
        - absolute_path: 绝对路径
        - file_type: 文件类型 (project/entrypoint/dependency/config/static/other)
        - size: 文件大小 (字节)
        - language: 编程语言 (python/javascript/typescript 等)
        - is_entrypoint: 是否为主入口文件

    使用场景:
        - 文件列表展示
        - 文件内容查看
        - 项目结构分析
        - 下载文件

    文件类型说明:
        - project: 项目配置文件 (package.json, requirements.txt)
        - entrypoint: 主入口文件 (main.py, index.js)
        - dependency: 依赖文件 (utils.py, helpers.ts)
        - config: 配置文件 (.env, config.json)
        - static: 静态资源 (css, 图片等)
        - other: 其他文件
    """

    __tablename__ = "session_files"

    # 会话 ID
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话ID",
    )

    # 文件路径 (相对于 tasks 目录)
    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="文件路径",
    )

    # 绝对路径 (可选)
    absolute_path: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
        comment="绝对路径",
    )

    # 文件类型
    file_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="文件类型: project/entrypoint/dependency/config/static/other",
    )

    # 文件大小 (字节)
    size: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="文件大小",
    )

    # 语言/技术栈 (可选，如 python, javascript, html)
    language: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="语言/技术栈",
    )

    # 是否是主入口文件
    is_entrypoint: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否主入口文件",
    )

    __table_args__ = (
        Index("ix_session_files_session", "session_id", "created_at"),
        {"comment": "会话文件表"},
    )
