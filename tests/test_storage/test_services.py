"""Test Storage services."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestStorageFactory:
    """Test storage factory"""

    def test_create_cos_storage(self):
        """测试创建腾讯云存储"""
        from app.storage.factory import StorageFactory

        storage = StorageFactory.create_storage(
            "cos",
            secret_id="test-id",
            secret_key="test-key",
            bucket="test-bucket",
            region="ap-guangzhou"
        )
        assert storage is not None

    def test_create_oss_storage(self):
        """测试创建阿里云存储"""
        from app.storage.factory import StorageFactory

        storage = StorageFactory.create_storage(
            "oss",
            access_key_id="test-id",
            access_key_secret="test-key",
            bucket="test-bucket",
            region="oss-cn-hangzhou"
        )
        assert storage is not None


class TestImageGenerator:
    """Test image generation"""

    def test_generate_image(self):
        """测试图像生成"""
        from app.storage.image import ImageGenerator

        generator = ImageGenerator(api_key="test-key", provider="dall-e")
        assert generator is not None
