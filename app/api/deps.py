"""
API 依赖项模块

定义 FastAPI 依赖项，如数据库会话、当前用户等。
这些依赖项可以在路由函数中直接注入使用。
"""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal
from app.core.security import verify_access_token
from app.core.exceptions import (
    UnauthorizedException, InvalidTokenException,
    InsufficientPermissionsException,
)
from app.models.user import User


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

    用 async with 确定性关闭会话。旧写法 `async for ... yield` 在 break 时
    连接滞留到 GC 才归还，连接池耗尽后落库会静默失败
    （2026-11-10 线上 create-session 不落库的根因之一）。
    """
    async with AsyncSessionLocal() as session:
        yield session


# =============================================
# 当前用户依赖
# =============================================

async def _provision_user(db: AsyncSession, payload: dict, username: str) -> Optional[int]:
    """按 token 声明在 LG 用户表自动建号（SSO 建号；撞号时降级改名重试一次）"""
    from app.models.user import UserRole, UserStatus

    sub = str(payload.get("sub", ""))
    try:
        role = UserRole(payload.get("role", "user"))
    except ValueError:
        role = UserRole.USER

    candidates = [
        (username, f"sso_{sub or username}@agproxy.local"),
        (f"{username}_{sub}", f"sso_{sub or username}_b@agproxy.local"),
    ]
    for uname, email in candidates:
        try:
            user = User(
                username=uname,
                email=email,
                nickname=username,
                hashed_password="!",
                role=role,
                status=UserStatus.ACTIVE,
                email_verified=False,
                login_failures=0,
            )
            db.add(user)
            await db.flush()
            uid = user.id
            await db.commit()
            return uid
        except IntegrityError:
            await db.rollback()
        except Exception:
            await db.rollback()
            return None
    return None


async def _resolve_user_id(db: AsyncSession, payload: dict) -> Optional[int]:
    """
    跨后端身份映射：优先按 username 认人——AG/LG 用户库独立、id 会撞号
    （实证 AG qi.yunhe id=2 = LG e2emt319947），禁止拿裸 id 直接当外键；
    查不到则按 token 声明自动建号，保证有效 token 一定能绑定到真实用户行，
    不再"看似登录、实则匿名"静默丢会话。
    """
    sub = str(payload.get("sub", ""))
    username = payload.get("username")

    # 有 username 声明（AG 签发的 token）：按 username 认人
    if username:
        row = (
            await db.execute(select(User).where(User.username == username))
        ).scalars().first()
        if row is not None:
            return row.id
        return await _provision_user(db, payload, username)

    # 无 username 声明（LG 自签 token，sub 即 LG 用户 id）：按 id 查行
    if sub.isdigit():
        row = await db.get(User, int(sub))
        if row is not None:
            return row.id
    return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    获取当前认证用户

    从请求头中提取 Bearer Token，验证并返回用户信息字典。
    适用于需要认证的路由。
    """
    if credentials is None:
        raise UnauthorizedException(
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_access_token(token)

    if payload is None:
        raise InvalidTokenException(
            detail="无效的访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise InvalidTokenException(
            detail="令牌中缺少用户标识",
            headers={"WWW-Authenticate": "Bearer"},
        )

    lg_user_id = await _resolve_user_id(db, payload)
    if lg_user_id is None:
        # 身份无法映射（建号失败等）：按鉴权失败处理，避免静默落匿名丢数据
        raise UnauthorizedException(
            detail="用户身份无法映射，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "id": lg_user_id,
        "username": payload.get("username", "anonymous"),
        "role": payload.get("role", "user"),
    }


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> Optional[dict]:
    """
    获取当前用户（可选）

    如果没有 Token，返回 None 而不是抛出异常。
    """
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials, db)
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
        raise InsufficientPermissionsException(detail="需要管理员权限")
    return current_user


# =============================================
# 类型别名
# =============================================

DBSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[dict, Depends(get_current_user)]
CurrentAdminUser = Annotated[dict, Depends(get_current_admin_user)]
OptionalCurrentUser = Annotated[Optional[dict], Depends(get_current_user_optional)]
