"""
安全认证模块

提供 JWT 令牌生成、密码哈希、验证码等安全相关功能。
使用 passlib 处理密码哈希，python-jose 处理 JWT。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# 密码哈希上下文，使用 bcrypt 算法
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SecurityManager:
    """
    安全管理器

    封装所有安全相关的操作，包括：
    - 密码哈希与验证
    - JWT 令牌创建与验证
    """

    def __init__(self):
        self.settings = get_settings()

    # =========================================
    # 密码操作
    # =========================================
    def hash_password(self, password: str) -> str:
        """
        对密码进行哈希处理

        使用 bcrypt 算法单向哈希，无法反向解密。
        每次调用生成不同的盐值，安全性更高。
        """
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        验证密码是否正确

        自动处理盐值，无需手动比较。
        """
        return pwd_context.verify(plain_password, hashed_password)

    # =========================================
    # JWT 操作
    # =========================================
    def create_access_token(
        self,
        subject: str,
        expires_delta: Optional[timedelta] = None,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        创建访问令牌 (Access Token)

        Args:
            subject: 令牌主题，通常是用户ID或邮箱
            expires_delta: 自定义过期时间，不指定则使用默认配置
            extra_claims: 额外的声明数据

        Returns:
            编码后的 JWT 字符串
        """
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=self.settings.access_token_expire_minutes
            )

        # 构建令牌内容
        to_encode: Dict[str, Any] = {
            "exp": expire,           # 过期时间（标准声明）
            "sub": str(subject),     # 主题（标准声明）
            "type": "access",        # 令牌类型标识
        }

        # 添加额外声明（如角色、权限等）
        if extra_claims:
            to_encode.update(extra_claims)

        # 编码并签名
        encoded_jwt = jwt.encode(
            to_encode,
            self.settings.secret_key,
            algorithm=self.settings.algorithm,
        )
        return encoded_jwt

    def create_refresh_token(self, subject: str) -> str:
        """
        创建刷新令牌 (Refresh Token)

        刷新令牌有效期更长，用于获取新的访问令牌。
        """
        expire = datetime.now(timezone.utc) + timedelta(
            days=self.settings.refresh_token_expire_days
        )

        to_encode: Dict[str, Any] = {
            "exp": expire,
            "sub": str(subject),
            "type": "refresh",
        }

        encoded_jwt = jwt.encode(
            to_encode,
            self.settings.secret_key,
            algorithm=self.settings.algorithm,
        )
        return encoded_jwt

    def verify_token(self, token: str, expected_type: str = "access") -> Optional[Dict[str, Any]]:
        """
        验证并解码 JWT 令牌

        Args:
            token: JWT 字符串
            expected_type: 期望的令牌类型（access 或 refresh）

        Returns:
            解码后的声明字典，验证失败返回 None
        """
        try:
            payload = jwt.decode(
                token,
                self.settings.secret_key,
                algorithms=[self.settings.algorithm],
            )

            # 验证令牌类型
            token_type = payload.get("type")
            if token_type != expected_type:
                return None

            return payload

        except JWTError:
            # 令牌过期、签名错误等都会抛出 JWTError
            return None

    def decode_token(self, token: str) -> Optional[str]:
        """
        解码令牌并提取主题（用户标识）

        用于从令牌中获取用户ID或邮箱。
        """
        payload = self.verify_token(token)
        if payload is None:
            return None
        return payload.get("sub")


# 全局安全管理器实例
security_manager = SecurityManager()


# =============================================
# 便捷函数（可直接导入使用）
# =============================================
def hash_password(password: str) -> str:
    """快捷函数：哈希密码"""
    return security_manager.hash_password(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """快捷函数：验证密码"""
    return security_manager.verify_password(plain_password, hashed_password)


def create_access_token(subject: str, **kwargs) -> str:
    """快捷函数：创建访问令牌"""
    return security_manager.create_access_token(subject, **kwargs)


def create_refresh_token(subject: str) -> str:
    """快捷函数：创建刷新令牌"""
    return security_manager.create_refresh_token(subject)


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """快捷函数：验证访问令牌"""
    return security_manager.verify_token(token, expected_type="access")


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """快捷函数：验证刷新令牌"""
    return security_manager.verify_token(token, expected_type="refresh")
