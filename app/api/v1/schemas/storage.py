"""Storage Schema"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class StorageUploadResponse(BaseModel):
    """存储上传响应"""
    success: bool
    url: Optional[str] = None
    key: Optional[str] = None
    error: Optional[str] = None


class StorageFile(BaseModel):
    """存储文件"""
    key: str
    name: str
    size: int
    content_type: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None


class StorageListResponse(BaseModel):
    """存储列表响应"""
    files: List[Dict[str, Any]]
    total: int
