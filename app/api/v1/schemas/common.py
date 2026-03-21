"""
API v1 Schemas 通用模型
"""

from typing import Generic, TypeVar, Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field


T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="页码（从1开始）")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PageMeta(BaseModel):
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")
    total_items: int = Field(description="总条目数")
    total_pages: int = Field(description="总页数")
    has_next: bool = Field(description="是否有下一页")
    has_prev: bool = Field(description="是否有上一页")

    @classmethod
    def create(cls, page: int, page_size: int, total_items: int) -> "PageMeta":
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
    items: List[T] = Field(description="数据列表")
    meta: PageMeta = Field(description="分页元数据")


class ErrorDetail(BaseModel):
    field: str = Field(description="错误字段")
    message: str = Field(description="错误信息")


class ErrorResponse(BaseModel):
    success: bool = Field(default=False)
    error: str = Field(description="错误信息")
    error_code: Optional[str] = Field(default=None, description="错误码")
    details: Optional[List[ErrorDetail]] = Field(default=None, description="详细错误信息")


class SuccessResponse(BaseModel):
    success: bool = Field(default=True)
    message: str = Field(default="操作成功")
    data: Optional[Any] = Field(default=None, description="返回数据")
