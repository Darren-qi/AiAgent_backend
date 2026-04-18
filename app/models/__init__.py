"""
Models 模块 __init__.py

导出所有数据库模型。
导入顺序重要：基类 -> 用户 -> 文章。
"""

from app.db.base import Base, IDMixin, TimestampMixin, SoftDeleteMixin
from app.models.user import User, UserRole, UserStatus
from app.models.post import Post, PostStatus, PostVisibility
from app.models.experience import (
    ExperienceModel,
    SessionModel,
    TaskModel,
    SessionContext,
    SessionFile,
)
from app.models.execution_node import ExecutionNode

# Memory models - 导入以注册到 Base.metadata
from app.agent.memory.models import (  # noqa: F401
    ConversationMessage,
    SemanticFact,
    EpisodicEvent,
    WorkingMemory,
)

__all__ = [
    # Base
    "Base",
    "IDMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    # User
    "User",
    "UserRole",
    "UserStatus",
    # Post
    "Post",
    "PostStatus",
    "PostVisibility",
    # Experience
    "ExperienceModel",
    "SessionModel",
    "TaskModel",
    "SessionContext",
    "SessionFile",
    "ExecutionNode",
    # Memory
    "ConversationMessage",
    "SemanticFact",
    "EpisodicEvent",
    "WorkingMemory",
]
