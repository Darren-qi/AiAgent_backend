"""
数据库基础模型模块

定义所有模型的基类，供 SQLAlchemy 和 Alembic 使用。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    数据库模型基类

    所有数据库模型都应继承此类。
    提供通用字段和配置。
    """

    # 子类可通过此属性定义表前缀
    __table_args__ = {"extend_existing": True}


class TimestampMixin:
    """
    时间戳混入类

    提供 created_at 和 updated_at 两个时间戳字段。
    自动记录数据的创建和更新时间。
    """

    # 创建时间：首次插入时自动设置为当前时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )

    # 更新时间：每次更新时自动刷新
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class IDMixin:
    """
    主键 ID 混入类

    提供自增主键 id 字段。
    """

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="主键ID",
    )


class SoftDeleteMixin:
    """
    软删除混入类

    提供 deleted_at 字段用于软删除。
    软删除的数据不会自动从数据库中移除，
    而是将 deleted_at 设置为删除时间。
    """

    # 删除时间，为 NULL 表示未删除
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="删除时间（软删除）",
    )

    @property
    def is_deleted(self) -> bool:
        """判断是否已软删除"""
        return self.deleted_at is not None
