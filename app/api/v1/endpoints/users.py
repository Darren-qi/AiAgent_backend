"""
用户路由模块

处理用户相关的 API 端点：
- GET /users - 获取用户列表（管理员）
- GET /users/{id} - 获取用户详情
- PATCH /users/{id} - 更新用户信息
- PATCH /users/{id}/password - 修改密码
- DELETE /users/{id} - 删除用户（管理员）
"""

from fastapi import APIRouter, Query

from app.api.deps import DBSession, CurrentUser, CurrentAdminUser
from app.core.exceptions import BadRequestException
from app.models.user import UserRole, UserStatus
from app.schemas.user import (
    UserResponse,
    UserListResponse,
    UserUpdate,
    UserPasswordUpdate,
    UserAdminUpdate,
    UserLLMKeyUpdate,
    LLMKeyStatus,
)
from app.schemas.common import (
    PageMeta,
    PageResponse,
    SuccessResponse,
)
from app.services.user import UserService


router = APIRouter()


@router.get(
    "",
    response_model=PageResponse[UserListResponse],
    summary="获取用户列表",
    description="分页获取用户列表，支持搜索和筛选。仅管理员可访问。",
)
async def get_users(
    db: DBSession,
    admin: CurrentAdminUser,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    keyword: str = Query(default=None, description="搜索关键词"),
    role: UserRole = Query(default=None, description="按角色筛选"),
    status: UserStatus = Query(default=None, description="按状态筛选"),
    is_active: bool = Query(default=None, description="按激活状态筛选"),
) -> PageResponse[UserListResponse]:
    """
    获取用户列表

    仅管理员可访问。支持分页、关键词搜索和状态筛选。
    """
    user_service = UserService(db)
    users, total = await user_service.get_users_paginated(
        page=page,
        page_size=page_size,
        keyword=keyword,
        role=role,
        status=status,
        is_active=is_active,
    )

    items = [UserListResponse.model_validate(user) for user in users]
    meta = PageMeta.create(page=page, page_size=page_size, total_items=total)

    return PageResponse(items=items, meta=meta)


@router.get(
    "/profile/llm-key",
    response_model=LLMKeyStatus,
    summary="获取 DeepSeek Key 状态",
    description="获取当前用户自己的 DeepSeek API Key 配置状态（只回掩码，不回全文）。",
)
async def get_llm_key(
    db: DBSession,
    current_user: CurrentUser,
) -> LLMKeyStatus:
    """获取当前用户的 DeepSeek Key 状态"""
    user_service = UserService(db)
    user = await user_service.get_user_by_id(current_user["id"])
    key = (user.deepseek_api_key if user else "") or ""
    from app.agent.llm.user_api_key import mask_key
    return LLMKeyStatus(configured=bool(key), masked=mask_key(key) or None)


@router.put(
    "/profile/llm-key",
    response_model=LLMKeyStatus,
    summary="保存/清除 DeepSeek Key",
    description="保存当前用户自己的 DeepSeek API Key（保存前用 DeepSeek /models 验证）；"
                "api_key 传空串表示清除、回落系统 Key。",
)
async def put_llm_key(
    key_data: UserLLMKeyUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> LLMKeyStatus:
    """保存或清除当前用户的 DeepSeek Key"""
    from app.agent.llm.user_api_key import mask_key, validate_deepseek_key

    key = (key_data.api_key or "").strip()
    if key:
        # 验证失败以 200 + error 返回（前端拦截器只读 message 字段，
        # 抛 400 会丢掉「Key 无效」这类具体原因）
        ok, msg = await validate_deepseek_key(key)
        if not ok:
            return LLMKeyStatus(configured=False, masked=None, error=msg)

    user_service = UserService(db)
    user = await user_service.get_user_by_id(current_user["id"])
    if user is None:
        raise BadRequestException(detail="用户不存在")
    user.deepseek_api_key = key or None
    await db.commit()
    await db.refresh(user)
    return LLMKeyStatus(configured=bool(key), masked=mask_key(key) or None)


# 注意：/profile/llm-key 必须注册在 /profile/{user_id} 之前——
# FastAPI 按路径正则先命中 {user_id}，随后 int 转换失败返回 422，
# 不会继续匹配后面的静态路由（本地 e2e 实测 GET /profile/llm-key 422）。
@router.get(
    "/profile/{user_id}",
    response_model=UserResponse,
    summary="获取用户公开资料",
    description="获取指定用户的公开资料信息。",
)
async def get_user_profile(
    user_id: int,
    db: DBSession,
) -> UserResponse:
    """
    获取用户公开资料

    任何人都可以访问。
    """
    user_service = UserService(db)
    user = await user_service.get_user_by_id(user_id)

    return UserResponse.model_validate(user)


@router.patch(
    "/profile",
    response_model=UserResponse,
    summary="更新当前用户信息",
    description="更新当前登录用户的基本信息。",
)
async def update_current_user(
    user_data: UserUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> UserResponse:
    """
    更新当前用户信息

    只能更新自己的信息。
    """
    user_service = UserService(db)
    user = await user_service.update_user(current_user["id"], user_data)

    return UserResponse.model_validate(user)


@router.patch(
    "/profile/password",
    response_model=SuccessResponse,
    summary="修改密码",
    description="修改当前用户的密码。",
)
async def change_password(
    password_data: UserPasswordUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> SuccessResponse:
    """
    修改密码

    需要提供旧密码进行验证。
    """
    user_service = UserService(db)
    await user_service.update_password(
        user_id=current_user["id"],
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )

    return SuccessResponse(message="密码修改成功")


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="管理员更新用户",
    description="管理员可更新任意用户的信息。",
)
async def admin_update_user(
    user_id: int,
    admin_data: UserAdminUpdate,
    db: DBSession,
    admin: CurrentAdminUser,
) -> UserResponse:
    """
    管理员更新用户

    管理员可以更新用户的角色、状态和昵称。
    """
    user_service = UserService(db)
    user = await user_service.admin_update_user(user_id, admin_data)

    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}",
    response_model=SuccessResponse,
    summary="删除用户",
    description="管理员可删除用户。",
)
async def delete_user(
    user_id: int,
    db: DBSession,
    admin: CurrentAdminUser,
) -> SuccessResponse:
    """
    删除用户

    管理员可以删除用户（软删除）。
    """
    if user_id == admin.id:
        raise BadRequestException(detail="不能删除自己")

    user_service = UserService(db)
    await user_service.delete_user(user_id)

    return SuccessResponse(message="用户已删除")
