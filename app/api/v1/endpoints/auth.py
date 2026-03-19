"""
认证路由模块

处理用户认证相关的 API 端点：
- POST /auth/register - 用户注册
- POST /auth/login - 用户登录
- POST /auth/refresh - 刷新令牌
- POST /auth/logout - 用户登出
- POST /auth/password-reset - 请求密码重置
- GET /auth/me - 获取当前用户信息
"""

from fastapi import APIRouter, status

from app.api.deps import DBSession, CurrentUser
from app.core.exceptions import BadRequestException
from app.schemas.user import UserCreate, UserResponse
from app.schemas.token import Token, TokenRefreshRequest
from app.schemas.common import SuccessResponse
from app.services.auth import AuthService


router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="用户注册",
    description="创建新用户账号，返回用户信息和访问令牌。",
)
async def register(
    user_data: UserCreate,
    db: DBSession,
) -> UserResponse:
    """
    用户注册

    - **username**: 用户名（3-50字符，唯一）
    - **email**: 邮箱地址（唯一）
    - **password**: 密码（至少8字符）
    - **nickname**: 昵称（可选）
    """
    auth_service = AuthService(db)
    user, token = await auth_service.register(user_data)

    # 返回用户信息（令牌通过响应头返回）
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=UserResponse,
    summary="用户登录",
    description="使用用户名或邮箱和密码登录，返回用户信息和访问令牌。",
)
async def login(
    username_or_email: str,
    password: str,
    db: DBSession,
) -> UserResponse:
    """
    用户登录

    支持使用用户名或邮箱登录。
    """
    auth_service = AuthService(db)
    user, token = await auth_service.login(username_or_email, password)

    # 返回用户信息和令牌（令牌可通过响应头获取）
    return UserResponse.model_validate(user)


@router.post(
    "/refresh",
    response_model=Token,
    summary="刷新令牌",
    description="使用刷新令牌获取新的访问令牌。",
)
async def refresh_token(
    request: TokenRefreshRequest,
    db: DBSession,
) -> Token:
    """
    刷新访问令牌

    提供有效的刷新令牌，获取新的访问令牌和刷新令牌。
    """
    auth_service = AuthService(db)
    return await auth_service.refresh_token(request.refresh_token)


@router.post(
    "/logout",
    response_model=SuccessResponse,
    summary="用户登出",
    description="用户登出（客户端应删除本地令牌）。",
)
async def logout(
    current_user: CurrentUser,
) -> SuccessResponse:
    """
    用户登出

    注意：此为无状态 JWT 认证，实际登出在客户端完成
    （删除本地存储的令牌）。服务端可通过加入黑名单实现。
    """
    return SuccessResponse(message="已成功登出")


@router.post(
    "/password-reset",
    response_model=SuccessResponse,
    summary="请求密码重置",
    description="通过邮箱请求密码重置链接。",
)
async def request_password_reset(
    email: str,
    db: DBSession,
) -> SuccessResponse:
    """
    请求密码重置

    如果邮箱存在，向该邮箱发送密码重置链接。
    为防止枚举攻击，即使邮箱不存在也返回成功。
    """
    auth_service = AuthService(db)
    await auth_service.generate_password_reset_token(email)

    return SuccessResponse(
        message="如果邮箱存在，重置链接已发送到您的邮箱"
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="获取当前用户",
    description="获取当前登录用户的信息。",
)
async def get_current_user_info(
    current_user: CurrentUser,
) -> UserResponse:
    """
    获取当前用户信息

    需要有效的访问令牌。
    """
    return UserResponse.model_validate(current_user)
