"""
通用 Schema 模块

定义跨多个资源使用的通用 Pydantic 模型，
如分页、响应包装等。
"""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


# =============================================
# 泛型定义
# =============================================

T = TypeVar("T")


# =============================================
# 分页相关
# =============================================

class PaginationParams(BaseModel):
    """
    分页参数

    用于接收分页请求参数。
    """

    page: int = Field(default=1, ge=1, description="页码（从1开始）")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")

    @property
    def offset(self) -> int:
        """计算 OFFSET 值"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """计算 LIMIT 值"""
        return self.page_size


class PageMeta(BaseModel):
    """
    分页元数据

    包含分页导航所需的全部信息。
    """

    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")
    total_items: int = Field(description="总条目数")
    total_pages: int = Field(description="总页数")
    has_next: bool = Field(description="是否有下一页")
    has_prev: bool = Field(description="是否有上一页")

    @classmethod
    def create(
        cls,
        page: int,
        page_size: int,
        total_items: int,
    ) -> "PageMeta":
        """工厂方法：从分页参数创建元数据"""
        total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
        return cls(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )


class PageResponse(BaseModel, Generic[T]):
    """
    分页响应

    通用分页响应格式，包含数据和元数据。
    """

    model_config = ConfigDict(from_attributes=True)

    items: List[T] = Field(description="数据列表")
    meta: PageMeta = Field(description="分页元数据")


# =============================================
# 响应包装
# =============================================

class ResponseWrapper(BaseModel, Generic[T]):
    """
    统一响应包装

    将响应数据包装在统一的格式中。
    """

    success: bool = Field(default=True, description="请求是否成功")
    data: Optional[T] = Field(default=None, description="响应数据")
    message: Optional[str] = Field(default=None, description="提示信息")
    error: Optional[str] = Field(default=None, description="错误信息")


class SuccessResponse(BaseModel):
    """
    操作成功响应

    用于不需要返回数据的成功操作。
    """

    success: bool = Field(default=True)
    message: str = Field(default="操作成功")


class ErrorResponse(BaseModel):
    """
    操作失败响应

    用于返回错误信息。
    """

    success: bool = Field(default=False)
    error: str = Field(description="错误信息")
    error_code: Optional[str] = Field(default=None, description="错误码")
    details: Optional[Dict[str, Any]] = Field(default=None, description="详细错误信息")


# =============================================
# 基础字段类
# =============================================

class IDSchema(BaseModel):
    """仅包含 ID 的 Schema"""
    id: int = Field(description="资源ID")


class TimestampSchema(BaseModel):
    """包含时间戳的 Schema"""
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class SoftDeleteSchema(BaseModel):
    """包含软删除字段的 Schema"""
    model_config = ConfigDict(from_attributes=True)

    deleted_at: Optional[datetime] = Field(default=None, description="删除时间")


# =============================================
# 类型别名
# =============================================
