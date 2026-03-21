"""对象存储工厂"""

from typing import Optional, Dict, Any


class StorageFactory:
    """对象存储工厂类"""

    @staticmethod
    def create_storage(
        provider: str,
        **kwargs
    ):
        """创建存储实例"""
        if provider == "cos":
            from app.storage.providers.cos import COSStorage
            return COSStorage(**kwargs)
        elif provider == "oss":
            from app.storage.providers.oss import OSSStorage
            return OSSStorage(**kwargs)
        elif provider == "bos":
            from app.storage.providers.bos import BOSStorage
            return BOSStorage(**kwargs)
        elif provider == "minio":
            from app.storage.providers.minio import MinIOStorage
            return MinIOStorage(**kwargs)
        elif provider == "local":
            from app.storage.providers.local import LocalStorage
            return LocalStorage(**kwargs)
        else:
            raise ValueError(f"不支持的存储提供者: {provider}")
