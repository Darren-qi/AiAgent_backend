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


# =============================================
# 安全认证
# =============================================

# Bearer Token 认证方案
bearer_scheme = HTTPBearer(auto_error=False)


# =============================================
# 数据库会话依赖
# =============================================

async def get_db_session():
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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    获取当前认证用户

    从请求头中提取 Bearer Token，验证并返回用户信息字典。
    适用于需要认证的路由。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌中缺少用户标识",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "id": int(user_id) if user_id.isdigit() else user_id,
        "username": payload.get("username", "anonymous"),
        "role": payload.get("role", "user"),
    }


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    """
    获取当前用户（可选）

    如果没有 Token，返回 None 而不是抛出异常。
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


# =============================================
# 管理员权限依赖
# =============================================

async def get_current_admin_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    获取当前管理员用户

    验证当前用户是否具有管理员权限。
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


# =============================================
# 类型别名
# =============================================

DBSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[dict, Depends(get_current_user)]
CurrentAdminUser = Annotated[dict, Depends(get_current_admin_user)]
OptionalCurrentUser = Annotated[Optional[dict], Depends(get_current_user_optional)]
