"""
用户服务模块
"""

from typing import List, Optional, Tuple
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, UserStatus
from app.schemas.user import UserCreate, UserUpdate, UserAdminUpdate
from app.core.security import hash_password, verify_password


class UserService:
    """用户服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """根据 ID 获取用户"""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_user(self, identifier: str) -> Optional[User]:
        """根据用户名或邮箱获取用户"""
        user = await self.get_user_by_username(identifier)
        if user:
            return user
        return await self.get_user_by_email(identifier)

    async def create_user(self, user_data: UserCreate) -> User:
        """创建新用户"""
        from datetime import datetime, timezone
        hashed_password = hash_password(user_data.password)
        now = datetime.now(timezone.utc)
        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hashed_password,
            nickname=user_data.nickname,
            created_at=now,
            updated_at=now,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def verify_user(self, username: str, password: str) -> Optional[User]:
        """验证用户登录"""
        user = await self.get_user_by_username(username)
        if user and verify_password(password, user.hashed_password):
            return user
        return None

    async def authenticate(self, username_or_email: str, password: str) -> Optional[User]:
        """根据用户名/邮箱和密码认证用户"""
        user = await self.get_user(username_or_email)
        if user and verify_password(password, user.hashed_password):
            return user
        return None

    async def update_user(self, user_id: int, user_data: UserUpdate) -> Optional[User]:
        """更新用户信息"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None
        update_data = user_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        """修改密码"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return False
        if not verify_password(old_password, user.hashed_password):
            return False
        user.hashed_password = hash_password(new_password)
        await self.db.commit()
        return True

    async def admin_update_user(self, user_id: int, admin_data: UserAdminUpdate) -> Optional[User]:
        """管理员更新用户"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None
        update_data = admin_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete_user(self, user_id: int) -> bool:
        """删除用户（软删除）"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return False
        from datetime import datetime, timezone
        user.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    async def get_users_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[User], int]:
        """分页获取用户列表"""
        query = select(User).where(User.deleted_at.is_(None))

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

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(User.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        users = result.scalars().all()

        return list(users), total
