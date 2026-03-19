"""
文章模型模块

定义文章相关的数据库模型。
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, String, Text, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IDMixin, TimestampMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.user import User


class PostStatus(str, Enum):
    """文章状态枚举"""
    DRAFT = "draft"           # 草稿
    PUBLISHED = "published"   # 已发布
    ARCHIVED = "archived"     # 已归档


class PostVisibility(str, Enum):
    """文章可见性枚举"""
    PUBLIC = "public"         # 公开
    PRIVATE = "private"       # 仅自己可见
    MEMBERS_ONLY = "members_only"  # 仅会员可见


class Post(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """
    文章模型

    包含文章的全部信息。
    支持软删除、草稿/发布状态、多种可见性。
    """

    __tablename__ = "posts"

    # =========================================
    # 基本信息
    # =========================================

    # 文章标题
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="文章标题",
    )

    # 文章内容（支持富文本或 Markdown）
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="文章内容",
    )

    # 摘要（可选，用于列表展示）
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="文章摘要",
    )

    # 封面图片 URL
    cover_image: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="封面图片URL",
    )

    # =========================================
    # 分类和标签
    # =========================================

    # 分类
    category: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="文章分类",
    )

    # 标签（逗号分隔的字符串）
    tags: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="文章标签（逗号分隔）",
    )

    # =========================================
    # 状态和可见性
    # =========================================

    # 文章状态
    status: Mapped[PostStatus] = mapped_column(
        String(20),
        default=PostStatus.DRAFT,
        nullable=False,
        index=True,
        comment="文章状态",
    )

    # 可见性
    visibility: Mapped[PostVisibility] = mapped_column(
        String(20),
        default=PostVisibility.PUBLIC,
        nullable=False,
        comment="可见性",
    )

    # =========================================
    # 统计信息
    # =========================================

    # 阅读量
    view_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="阅读量",
    )

    # 点赞数
    like_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="点赞数",
    )

    # 评论数（可由计数字段或关联表计算得出）
    comment_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="评论数",
    )

    # =========================================
    # SEO 相关
    # =========================================

    # SEO 友好的 URL slug
    slug: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="URL Slug",
    )

    # Meta 描述（SEO）
    meta_description: Mapped[Optional[str]] = mapped_column(
        String(160),
        nullable=True,
        comment="Meta描述",
    )

    # =========================================
    # 时间和版本控制
    # =========================================

    # 发布时间（可选，草稿状态下为空）
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="发布时间",
    )

    # =========================================
    # 外键关系
    # =========================================

    # 作者 ID
    author_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="作者ID",
    )

    # =========================================
    # 关系
    # =========================================

    # 文章作者（多对一）
    author: Mapped["User"] = relationship(
        "User",
        back_populates="posts",
        foreign_keys=[author_id],
    )

    # =========================================
    # 属性方法
    # =========================================

    @property
    def is_published(self) -> bool:
        """判断文章是否已发布"""
        return self.status == PostStatus.PUBLISHED

    @property
    def is_draft(self) -> bool:
        """判断是否为草稿"""
        return self.status == PostStatus.DRAFT

    @property
    def tag_list(self) -> List[str]:
        """获取标签列表"""
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    def __repr__(self) -> str:
        return f"<Post(id={self.id}, title='{self.title}', status='{self.status}')>"
