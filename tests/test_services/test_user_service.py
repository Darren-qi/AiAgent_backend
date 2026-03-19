"""
用户服务测试

测试用户服务的业务逻辑。
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.core.exceptions import NotFoundException, AlreadyExistsException
from app.services.user import UserService
from app.schemas.user import UserCreate, UserUpdate
from app.models.user import UserRole, UserStatus


class TestUserService:
    """用户服务测试类"""

    @pytest.mark.asyncio
    async def test_create_user(self, db_session: AsyncSession):
        """测试创建用户"""
        service = UserService(db_session)
        user_data = UserCreate(
            username="newuser",
            email="new@example.com",
            password="password123",
            nickname="New User",
        )

        user = await service.create_user(user_data)

        assert user.id is not None
        assert user.username == "newuser"
        assert user.email == "new@example.com"
        assert verify_password("password123", user.hashed_password)

    @pytest.mark.asyncio
    async def test_create_duplicate_username(self, db_session: AsyncSession):
        """测试创建重复用户名"""
        service = UserService(db_session)

        # 创建第一个用户
        await service.create_user(UserCreate(
            username="duplicate",
            email="first@example.com",
            password="password123",
        ))

        # 尝试创建重复用户名
        with pytest.raises(AlreadyExistsException):
            await service.create_user(UserCreate(
                username="duplicate",
                email="second@example.com",
                password="password123",
            ))

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, db_session: AsyncSession):
        """测试根据 ID 获取用户"""
        service = UserService(db_session)

        # 创建用户
        created = await service.create_user(UserCreate(
            username="gettest",
            email="gettest@example.com",
            password="password123",
        ))

        # 获取用户
        user = await service.get_user_by_id(created.id)

        assert user.id == created.id
        assert user.username == "gettest"

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, db_session: AsyncSession):
        """测试获取不存在的用户"""
        service = UserService(db_session)

        with pytest.raises(NotFoundException):
            await service.get_user_by_id(99999)

    @pytest.mark.asyncio
    async def test_update_user(self, db_session: AsyncSession):
        """测试更新用户"""
        service = UserService(db_session)

        # 创建用户
        user = await service.create_user(UserCreate(
            username="updatetest",
            email="update@example.com",
            password="password123",
        ))

        # 更新用户
        updated = await service.update_user(user.id, UserUpdate(
            nickname="New Nickname",
            bio="New bio text",
        ))

        assert updated.nickname == "New Nickname"
        assert updated.bio == "New bio text"
        assert updated.username == "updatetest"  # 未更新的字段保持不变

    @pytest.mark.asyncio
    async def test_update_password(self, db_session: AsyncSession):
        """测试更新密码"""
        service = UserService(db_session)

        # 创建用户
        user = await service.create_user(UserCreate(
            username="pwtest",
            email="pwtest@example.com",
            password="oldpassword",
        ))

        # 更新密码
        await service.update_password(
            user.id,
            old_password="oldpassword",
            new_password="newpassword",
        )

        # 验证新密码
        updated_user = await service.get_user_by_id(user.id)
        assert verify_password("newpassword", updated_user.hashed_password)
        assert not verify_password("oldpassword", updated_user.hashed_password)

    @pytest.mark.asyncio
    async def test_authenticate_success(self, db_session: AsyncSession):
        """测试认证成功"""
        service = UserService(db_session)

        # 创建用户
        await service.create_user(UserCreate(
            username="authtest",
            email="auth@example.com",
            password="password123",
        ))

        # 认证
        user = await service.authenticate("authtest", "password123")

        assert user.username == "authtest"

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(self, db_session: AsyncSession):
        """测试密码错误"""
        service = UserService(db_session)

        # 创建用户
        await service.create_user(UserCreate(
            username="pwauthtest",
            email="pwauth@example.com",
            password="password123",
        ))

        # 尝试错误密码
        with pytest.raises(Exception):  # BadRequestException
            await service.authenticate("pwauthtest", "wrongpassword")

    @pytest.mark.asyncio
    async def test_authenticate_nonexistent_user(self, db_session: AsyncSession):
        """测试用户不存在"""
        service = UserService(db_session)

        with pytest.raises(Exception):
            await service.authenticate("nonexistent", "password123")
