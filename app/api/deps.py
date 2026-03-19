"""
API 依赖项模块

定义 FastAPI 依赖项，如数据库会话、当前用户等。
这些依赖项可以在路由函数中直接注入使用。
"""

from typing import Annotated, Generator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.security import verify_access_token
from app.core.exceptions import (
    InvalidTokenException,
    TokenExpiredException,
    UnauthorizedException,
    ForbiddenException,
)
from app.models.user import User
from app.services.user import UserService


# =============================================
# 安全认证
# =============================================

# Bearer Token 认证方案
bearer_scheme = HTTPBearer(auto_error=False)


# =============================================
# 数据库会话依赖
# =============================================

async def get_db_session() -> Generator[AsyncSession, None, None]:
    """
    数据库会话依赖

    直接使用 get_db，返回 AsyncSession。
    """
    async for session in get_db():
        yield session


# =============================================
# 当前用户依赖
# =============================================

async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)] = None,
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """
    获取当前认证用户

    从请求头中提取 Bearer Token，验证并返回用户。
    适用于需要认证的路由。
    """
    if credentials is None:
        raise UnauthorizedException(detail="请先登录")

    token = credentials.credentials
    payload = verify_access_token(token)

    if payload is None:
        raise InvalidTokenException(detail="无效的访问令牌")

    user_id: str = payload.get("sub")
    if user_id is None:
        raise InvalidTokenException(detail="令牌中缺少用户标识")

    try:
        user_id = int(user_id)
    except ValueError:
        raise InvalidTokenException(detail="无效的用户标识")

    user_service = UserService(db)
    try:
        user = await user_service.get_user_by_id(user_id)
    except Exception:
        raise UnauthorizedException(detail="用户不存在")

    return user


async def get_current_user_optional(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)] = None,
    db: AsyncSession = Depends(get_db_session),
) -> Optional[User]:
    """
    获取当前用户（可选）

    如果没有 Token，返回 None 而不是抛出异常。
    适用于公开路由但可能需要用户信息的场景。
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials, db)
    except (UnauthorizedException, InvalidTokenException, TokenExpiredException):
        return None


# =============================================
# 管理员权限依赖
# =============================================

async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    获取当前管理员用户

    验证当前用户是否具有管理员权限。
    """
    if not current_user.is_admin:
        raise ForbiddenException(detail="需要管理员权限")

    return current_user


# =============================================
# 类型别名
# =============================================

DBSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdminUser = Annotated[User, Depends(get_current_admin_user)]
OptionalCurrentUser = Annotated[Optional[User], Depends(get_current_user_optional)]
