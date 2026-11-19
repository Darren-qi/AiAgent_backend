"""Storage Schema"""

from typing import Any

from pydantic import BaseModel


class StorageUploadResponse(BaseModel):
    """存储上传响应"""
    success: bool
    url: str | None = None
    key: str | None = None
    error: str | None = None


class StorageFile(BaseModel):
    """存储文件"""
    key: str
    name: str
    size: int
    content_type: str | None = None
    url: str | None = None
    created_at: str | None = None


class StorageListResponse(BaseModel):
    """存储列表响应"""
    files: list[dict[str, Any]]
    total: int
