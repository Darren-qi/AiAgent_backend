"""
用户服务模块

封装用户相关的业务逻辑。
所有数据库操作应放在这一层。
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password, verify_password
from app.core.exceptions import (
    NotFoundException,
    AlreadyExistsException,
    BadRequestException,
    UserInactiveException,
    UserBannedException,
)
from app.models.user import User, UserRole, UserStatus
from app.schemas.user import UserCreate, UserUpdate, UserAdminUpdate


class UserService:
    """
    用户服务类

    处理所有用户相关的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, user_data: UserCreate) -> User:
        """
        创建新用户

        验证用户名和邮箱的唯一性，然后创建用户。
        """
        # 检查用户名是否已存在
        existing = await self.get_user_by_username(user_data.username)
        if existing:
            raise AlreadyExistsException(resource="用户名", identifier=user_data.username)

        # 检查邮箱是否已存在
        existing = await self.get_user_by_email(user_data.email)
        if existing:
            raise AlreadyExistsException(resource="邮箱", identifier=user_data.email)

        # 创建用户对象
        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hash_password(user_data.password),
            nickname=user_data.nickname,
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def get_user_by_id(self, user_id: int) -> User:
        """
        根据 ID 获取用户

        如果用户不存在或已删除，抛出异常。
        """
        query = select(User).where(
            User.id == user_id,
            User.deleted_at.is_(None)
        )
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            raise NotFoundException(resource="用户", resource_id=user_id)

        return user

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户（包括已删除的）"""
        query = select(User).where(User.username == username.lower())
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户（包括已删除的）"""
        query = select(User).where(User.email == email.lower())
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_by_username_or_email(self, identifier: str) -> Optional[User]:
        """根据用户名或邮箱获取用户"""
        identifier = identifier.lower()
        query = select(User).where(
            or_(
                User.username == identifier,
                User.email == identifier,
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_user(self, user_id: int, user_data: UserUpdate) -> User:
        """
        更新用户信息

        只更新提供的字段。
        """
        user = await self.get_user_by_id(user_id)

        # 更新字段（只更新非 None 的字段）
        if user_data.nickname is not None:
            user.nickname = user_data.nickname
        if user_data.avatar is not None:
            user.avatar = user_data.avatar
        if user_data.bio is not None:
            user.bio = user_data.bio

        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def update_password(self, user_id: int, old_password: str, new_password: str) -> User:
        """
        更新用户密码

        验证旧密码后才能更新。
        """
        user = await self.get_user_by_id(user_id)

        # 验证旧密码
        if not verify_password(old_password, user.hashed_password):
            raise BadRequestException(detail="旧密码不正确")

        # 更新密码
        user.hashed_password = hash_password(new_password)

        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def admin_update_user(self, user_id: int, admin_data: UserAdminUpdate) -> User:
        """
        管理员更新用户

        包括修改角色和状态。
        """
        user = await self.get_user_by_id(user_id)

        if admin_data.role is not None:
            user.role = admin_data.role
        if admin_data.status is not None:
            user.status = admin_data.status
        if admin_data.nickname is not None:
            user.nickname = admin_data.nickname

        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def delete_user(self, user_id: int, hard: bool = False) -> None:
        """
        删除用户

        默认为软删除，hard=True 时执行硬删除。
        """
        user = await self.get_user_by_id(user_id)

        if hard:
            await self.db.delete(user)
        else:
            user.deleted_at = datetime.now(timezone.utc)

        await self.db.commit()

    async def get_users_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[User], int]:
        """
        分页获取用户列表

        支持关键词搜索、角色和状态筛选。
        """
        query = select(User).where(User.deleted_at.is_(None))

        # 应用过滤条件
        if keyword:
            keyword_filter = f"%{keyword}%"
            query = query.where(
                or_(
                    User.username.ilike(keyword_filter),
                    User.email.ilike(keyword_filter),
                    User.nickname.ilike(keyword_filter),
                )
            )

        if role:
            query = query.where(User.role == role)

        if status:
            query = query.where(User.status == status)

        if is_active is not None:
            if is_active:
                query = query.where(User.status == UserStatus.ACTIVE)
            else:
                query = query.where(User.status != UserStatus.ACTIVE)

        # 获取总数
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # 应用分页和排序
        query = query.order_by(User.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        users = result.scalars().all()

        return list(users), total

    async def authenticate(self, identifier: str, password: str) -> User:
        """
        用户认证

        支持用户名或邮箱登录。
        """
        user = await self.get_user_by_username_or_email(identifier)

        if not user:
            raise BadRequestException(detail="用户不存在")

        # 检查用户状态
        if user.status == UserStatus.INACTIVE:
            raise UserInactiveException()
        if user.status == UserStatus.BANNED:
            raise UserBannedException()

        # 验证密码
        if not verify_password(password, user.hashed_password):
            user.login_failures += 1
            await self.db.commit()
            raise BadRequestException(detail="密码错误")

        # 登录成功，重置失败计数
        user.login_failures = 0
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()

        return user

    async def update_login_info(self, user_id: int) -> None:
        """更新用户登录信息"""
        user = await self.get_user_by_id(user_id)
        user.last_login_at = datetime.now(timezone.utc)
        user.login_failures = 0
        await self.db.commit()
