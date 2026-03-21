"""Storage 测试"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.agent.tools.storage.manager import StorageManager, StorageProvider


class TestStorageManager:
    """存储管理器测试"""

    def test_create_manager(self):
        """测试创建管理器"""
        manager = StorageManager()
        assert manager is not None

    @pytest.mark.asyncio
    async def test_upload_local(self):
        """测试本地存储上传"""
        manager = StorageManager()
        result = await manager.upload_file(
            file_data=b"test content",
            filename="test.txt",
            content_type="text/plain",
        )
        assert result.success is True
        assert result.key is not None

    @pytest.mark.asyncio
    async def test_download(self):
        """测试文件下载"""
        manager = StorageManager()
        data = await manager.download_file("nonexistent.txt")
        assert data is None

    @pytest.mark.asyncio
    async def test_delete(self):
        """测试文件删除"""
        manager = StorageManager()
        deleted = await manager.delete_file("test.txt")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_files(self):
        """测试列出文件"""
        manager = StorageManager()
        files = await manager.list_files()
        assert isinstance(files, list)
