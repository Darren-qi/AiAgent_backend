"""
用户模型模块

定义用户相关的数据库模型。
包含普通用户模型。

数据库表:
    - users: 用户表
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, String, Text, Boolean, ForeignKey, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IDMixin, TimestampMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.post import Post


class UserRole(str, Enum):
    """用户角色枚举"""
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"


class UserStatus(str, Enum):
    """用户状态枚举"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"


class User(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """
    用户模型表 (users)

    存储用户的基本信息和认证相关字段。
    支持软删除和多种用户状态。

    主要字段:
        - username: 用户名 (唯一)
        - email: 邮箱 (唯一)
        - nickname: 昵称
        - avatar: 头像 URL
        - hashed_password: 密码哈希
        - role: 用户角色 (user/admin/moderator)
        - status: 用户状态 (active/inactive/banned)
        - email_verified: 邮箱是否已验证
        - login_failures: 连续登录失败次数
        - last_login_at: 最后登录时间

    使用场景:
        - 用户认证
        - 权限控制
        - 用户管理

    安全特性:
        - 密码哈希存储 (不存储明文)
        - 邮箱验证机制
        - 登录失败锁定
        - 软删除 (保留数据可恢复)
    """

    __tablename__ = "users"

    # =========================================
    # 基本信息
    # =========================================

    # 用户名（唯一）
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="用户名",
    )

    # 邮箱（唯一）
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="邮箱",
    )

    # 昵称（可选）
    nickname: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="昵称",
    )

    # 头像 URL
    avatar: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="头像URL",
    )

    # 个人简介
    bio: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="个人简介",
    )

    # =========================================
    # 认证信息
    # =========================================

    # 密码哈希（不存储明文密码）
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="密码哈希",
    )

    # 是否验证邮箱
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="邮箱是否已验证",
    )

    # 邮箱验证码令牌（用于验证流程）
    email_verification_token: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="邮箱验证令牌",
    )

    # 重置密码令牌
    password_reset_token: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="密码重置令牌",
    )

    # 重置令牌过期时间
    password_reset_expires: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="密码重置令牌过期时间",
    )

    # =========================================
    # 角色和状态
    # =========================================

    # 用户角色
    role: Mapped[UserRole] = mapped_column(
        String(20),
        default=UserRole.USER,
        nullable=False,
        comment="用户角色",
    )

    # 用户状态
    status: Mapped[UserStatus] = mapped_column(
        String(20),
        default=UserStatus.ACTIVE,
        nullable=False,
        comment="用户状态",
    )

    # =========================================
    # 统计信息
    # =========================================

    # 登录失败次数（用于账号锁定）
    login_failures: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        comment="连续登录失败次数",
    )

    # 最后登录时间
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最后登录时间",
    )

    # =========================================
    # 关系
    # =========================================

    # 用户发布的文章（一对多）
    posts: Mapped[List["Post"]] = relationship(
        "Post",
        back_populates="author",
        foreign_keys="Post.author_id",
    )

    # =========================================
    # 属性方法
    # =========================================

    @property
    def is_active(self) -> bool:
        """判断用户是否激活"""
        return self.status == UserStatus.ACTIVE

    @property
    def is_banned(self) -> bool:
        """判断用户是否被禁用"""
        return self.status == UserStatus.BANNED

    @property
    def is_admin(self) -> bool:
        """判断是否为管理员"""
        return self.role == UserRole.ADMIN

    @property
    def display_name(self) -> str:
        """获取显示名称（优先使用昵称）"""
        return self.nickname or self.username

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"
