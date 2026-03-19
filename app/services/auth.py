"""
认证服务模块

处理用户认证相关的业务逻辑，包括：
- 登录/登出
- Token 生成和验证
- 邮箱验证
- 密码重置
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
    hash_password,
)
from app.core.config import get_settings
from app.core.exceptions import (
    InvalidCredentialsException,
    TokenExpiredException,
    InvalidTokenException,
)
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import UserCreate
from app.services.user import UserService


class AuthService:
    """
    认证服务类

    处理所有认证相关的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_service = UserService(db)
        self.settings = get_settings()

    async def login(self, username_or_email: str, password: str) -> Tuple[User, Token]:
        """
        用户登录

        验证凭证，生成令牌。
        """
        # 验证用户凭证
        user = await self.user_service.authenticate(username_or_email, password)

        # 生成令牌
        token = self._create_tokens(str(user.id))

        return user, token

    async def register(self, user_data: UserCreate) -> Tuple[User, Token]:
        """
        用户注册

        创建新用户并生成令牌。
        """
        # 创建用户
        user = await self.user_service.create_user(user_data)

        # 生成令牌
        token = self._create_tokens(str(user.id))

        return user, token

    async def refresh_token(self, refresh_token: str) -> Token:
        """
        使用刷新令牌获取新的访问令牌

        验证刷新令牌有效性，生成新的访问令牌和刷新令牌。
        """
        # 验证刷新令牌
        payload = verify_refresh_token(refresh_token)
        if payload is None:
            raise InvalidTokenException(detail="无效的刷新令牌")

        user_id = payload.get("sub")
        if not user_id:
            raise InvalidTokenException(detail="无效的令牌载荷")

        # 获取用户
        user = await self.user_service.get_user_by_id(int(user_id))

        # 生成新令牌
        token = self._create_tokens(user_id)

        return token

    async def verify_token(self, token: str) -> dict:
        """
        验证访问令牌

        返回令牌载荷，失败则抛出异常。
        """
        payload = verify_access_token(token)
        if payload is None:
            raise TokenExpiredException()

        return payload

    def _create_tokens(self, user_id: str) -> Token:
        """
        创建访问令牌和刷新令牌

        根据配置生成双令牌。
        """
        # 生成访问令牌
        access_token = create_access_token(
            subject=user_id,
            expires_delta=timedelta(minutes=self.settings.access_token_expire_minutes),
        )

        # 生成刷新令牌
        refresh_token = create_refresh_token(subject=user_id)

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=self.settings.access_token_expire_minutes * 60,
        )

    async def generate_password_reset_token(self, email: str) -> Optional[str]:
        """
        生成密码重置令牌

        发送重置链接到用户邮箱。
        返回令牌用于后续验证。
        """
        user = await self.user_service.get_user_by_email(email)
        if not user:
            # 为防止枚举攻击，即使用户不存在也返回成功
            return None

        # 生成随机令牌
        reset_token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)

        # 保存到用户记录
        user.password_reset_token = hash_password(reset_token)
        user.password_reset_expires = expires
        await self.db.commit()

        # TODO: 发送邮件（可选功能）
        # if self.settings.smtp_enabled:
        #     await self._send_password_reset_email(user.email, reset_token)

        return reset_token

    async def reset_password(self, token: str, new_password: str) -> bool:
        """
        使用重置令牌设置新密码

        验证令牌有效性，设置新密码。
        """
        # TODO: 实现密码重置逻辑
        # 1. 查找使用此令牌的请求
        # 2. 验证令牌未过期
        # 3. 更新密码
        # 4. 使令牌失效
        pass

    async def generate_email_verification_token(self, user_id: int) -> Optional[str]:
        """
        生成邮箱验证令牌

        用于新用户注册后的邮箱验证。
        """
        user = await self.user_service.get_user_by_id(user_id)

        if user.email_verified:
            return None

        # 生成随机令牌
        verification_token = secrets.token_urlsafe(32)

        user.email_verification_token = hash_password(verification_token)
        await self.db.commit()

        return verification_token

    async def verify_email(self, user_id: int, token: str) -> bool:
        """
        验证邮箱

        验证邮箱验证令牌是否有效。
        """
        user = await self.user_service.get_user_by_id(user_id)

        if not user.email_verification_token:
            return False

        # 验证令牌
        if not verify_password(token, user.email_verification_token):
            return False

        # 更新用户状态
        user.email_verified = True
        user.email_verification_token = None
        await self.db.commit()

        return True
