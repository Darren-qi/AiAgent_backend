"""
记忆数据库模型

存储 Agent 执行过程中的各种记忆数据，采用多层次记忆架构：
- 短期记忆 (Short-term): 对话消息、工作记忆
- 长期记忆 (Long-term): 语义事实、情景事件

数据库表:
    - conversation_messages: 短期对话消息
    - semantic_facts: 结构化语义事实
    - episodic_events: 执行情景事件
    - working_memory: 当前任务工作记忆
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IDMixin, SoftDeleteMixin, TimestampMixin


class ConversationMessage(Base, IDMixin, TimestampMixin):
    """
    对话消息表 (conversation_messages)

    存储 Agent 与用户的对话历史，支持多轮对话上下文。
    用于短期记忆的对话缓冲，为 LLM 提供历史上下文。

    主要字段:
        - session_id: 所属会话ID
        - role: 消息角色 (user/assistant/system)
        - content: 消息内容
        - metadata: 额外元数据 (如 token 消耗、模型选择等)
        - sequence: 消息序号，用于保持顺序

    使用场景:
        - 加载历史对话到 LLM 上下文
        - 调试对话流程
        - 分析用户交互模式
    """

    __tablename__ = "conversation_messages"

    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="会话ID",
    )
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="角色: user/assistant/system",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="消息内容",
    )
    message_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="元数据",
    )
    sequence: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="消息序列号",
    )

    __table_args__ = (
        Index("ix_conversation_messages_session_sequence", "session_id", "sequence"),
        {"comment": "对话消息表"},
    )


class SemanticFact(Base, IDMixin, TimestampMixin):
    """
    语义事实表 (semantic_facts)

    存储从对话中提取的结构化知识/事实。
    属于长期记忆，用于跨会话保持重要信息。

    主要字段:
        - session_id: 所属会话ID
        - fact_key: 事实键 (唯一标识，如 "user_preference", "project_name")
        - fact_value: 事实值 (JSON 结构，支持任意类型)

    使用场景:
        - 存储用户偏好设置
        - 记住项目相关信息
        - 跨会话保持上下文

    示例:
        - fact_key: "favorite_language"
        - fact_value: {"value": "python", "confidence": 0.95}
    """

    __tablename__ = "semantic_facts"

    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="会话ID",
    )
    fact_key: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="事实键",
    )
    fact_value: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="事实值",
    )

    __table_args__ = (
        Index("ix_semantic_facts_session_key", "session_id", "fact_key", unique=True),
        {"comment": "语义事实表"},
    )


class EpisodicEvent(Base, IDMixin, TimestampMixin):
    """
    情景事件表 (episodic_events)

    存储 Agent 执行过程中的重要事件/经历。
    属于长期记忆，用于记录"发生了什么"。

    主要字段:
        - session_id: 所属会话ID
        - episode_id: 事件唯一标识 (UUID)
        - event_data: 事件数据 (JSON，包含动作、参数、结果等)
        - summary: 事件摘要 (可选，用于快速回顾)

    使用场景:
        - 记录关键执行步骤
        - 分析任务执行历史
        - 支持经验学习

    示例事件:
        - 文件创建事件: {action: "create_file", path: "main.py"}
        - API 调用事件: {action: "http_request", url: "...", status: 200}
        - 错误事件: {action: "error", error: "Connection timeout"}
    """

    __tablename__ = "episodic_events"

    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="会话ID",
    )
    episode_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        comment="事件唯一标识",
    )
    event_data: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="事件数据",
    )
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="事件摘要",
    )

    __table_args__ = (
        Index("ix_episodic_events_session_time", "session_id", "created_at"),
        {"comment": "情景事件表"},
    )


class WorkingMemory(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """
    工作记忆表 (working_memory)

    存储当前任务执行过程中的中间状态。
    是 Agent 的"工作台"，用于暂存需要跨步骤使用的数据。

    主要字段:
        - session_id: 所属会话ID
        - memory_key: 记忆键 (如 "current_file", "generated_code", "task_path")
        - memory_value: 记忆值 (JSON 结构)

    使用场景:
        - 存储当前文件路径供后续步骤使用
        - 暂存生成的文件内容
        - 传递任务上下文

    特点:
        - 支持软删除 (deleted_at 字段)
        - 使用 UPSERT 策略，自动更新已有记录
        - 与内存中的 WorkingMemory 类配合使用

    示例:
        - memory_key: "task_path", memory_value: {"path": "tasks/project_xxx"}
        - memory_key: "generated_files", memory_value: {"files": ["a.py", "b.py"]}
    """

    __tablename__ = "working_memory"

    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="会话ID",
    )
    memory_key: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="记忆键",
    )
    memory_value: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="记忆值",
    )

    __table_args__ = (
        Index("ix_working_memory_session_key", "session_id", "memory_key", unique=True),
        {"comment": "工作记忆表"},
    )
