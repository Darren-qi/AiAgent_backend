# -*- coding: utf-8 -*-
"""Storage 端点"""

from typing import Optional
from fastapi import APIRouter, UploadFile, File

from app.api.deps import DBSession, CurrentUser
from app.api.v1.schemas.storage import StorageUploadResponse, StorageListResponse
from app.agent.tools.storage.manager import StorageManager

router = APIRouter()
storage_manager = StorageManager()


@router.post("/upload", response_model=StorageUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    folder: str = "",
    user: CurrentUser = None,
) -> StorageUploadResponse:
    """上传文件"""
    contents = await file.read()

    result = await storage_manager.upload_file(
        file_data=contents,
        filename=file.filename,
        content_type=file.content_type,
        folder=folder or str(user["id"]) if user else "anonymous",
    )

    return StorageUploadResponse(
        success=result.get("success", False),
        url=result.get("url"),
        key=result.get("key"),
        error=result.get("error"),
    )


@router.get("/list", response_model=StorageListResponse)
async def list_files(
    prefix: str = "",
    limit: int = 100,
    user: CurrentUser = None,
) -> StorageListResponse:
    """列出文件"""
    files = await storage_manager.list_files(prefix=prefix, max_keys=limit)

    return StorageListResponse(
        files=files,
        total=len(files),
    )


@router.delete("/{key}")
async def delete_file(
    key: str,
    user: CurrentUser = None,
) -> dict:
    """删除文件"""
    deleted = await storage_manager.delete_file(key)
    return {"deleted": deleted, "key": key}


@router.get("/{key}/url")
async def get_file_url(
    key: str,
    expires: int = 3600,
    user: CurrentUser = None,
) -> dict:
    """获取文件访问 URL"""
    url = await storage_manager.get_file_url(key, expires)
    return {"url": url, "key": key, "expires": expires}
