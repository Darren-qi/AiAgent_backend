"""
文章路由模块

处理文章相关的 API 端点：
- GET /posts - 获取文章列表
- POST /posts - 创建文章
- GET /posts/{id} - 获取文章详情
- PATCH /posts/{id} - 更新文章
- DELETE /posts/{id} - 删除文章
- POST /posts/{id}/publish - 发布文章
- POST /posts/{id}/archive - 归档文章
"""

from fastapi import APIRouter, status, Query

from app.api.deps import DBSession, CurrentUser, CurrentAdminUser, OptionalCurrentUser
from app.models.post import PostStatus, PostVisibility
from app.schemas.post import (
    PostCreate,
    PostUpdate,
    PostPublish,
    PostResponse,
    PostListItem,
)
from app.schemas.common import (
    PageMeta,
    PageResponse,
    SuccessResponse,
)
from app.services.post import PostService


router = APIRouter()


@router.get(
    "",
    response_model=PageResponse[PostListItem],
    summary="获取文章列表",
    description="分页获取已发布的文章列表，支持多种筛选条件。",
)
async def get_posts(
    db: DBSession,
    current_user: OptionalCurrentUser,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    keyword: str = Query(default=None, description="搜索关键词"),
    category: str = Query(default=None, description="按分类筛选"),
    tag: str = Query(default=None, description="按标签筛选"),
    status: PostStatus = Query(default=None, description="按状态筛选"),
    author_id: int = Query(default=None, description="按作者筛选"),
) -> PageResponse[PostListItem]:
    """
    获取文章列表

    默认只返回已发布的文章。
    如果用户已登录，可以查看自己的所有文章（包括草稿）。
    """
    # 确定是否包含草稿
    include_drafts = False
    if current_user:
        include_drafts = True

    post_service = PostService(db)
    posts, total = await post_service.get_posts_paginated(
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        tag=tag,
        status=status,
        author_id=author_id,
        include_drafts=include_drafts,
    )

    items = [PostListItem.model_validate(post) for post in posts]
    meta = PageMeta.create(page=page, page_size=page_size, total_items=total)

    return PageResponse(items=items, meta=meta)


@router.post(
    "",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建文章",
    description="创建新文章（默认为草稿状态）。",
)
async def create_post(
    post_data: PostCreate,
    db: DBSession,
    current_user: CurrentUser,
) -> PostResponse:
    """
    创建文章

    需要登录。创建的文章默认为草稿状态。
    """
    post_service = PostService(db)
    post = await post_service.create_post(current_user.id, post_data)

    return PostResponse.model_validate(post)


@router.get(
    "/{post_id}",
    response_model=PostResponse,
    summary="获取文章详情",
    description="根据 ID 获取文章详情，同时增加阅读量。",
)
async def get_post(
    post_id: int,
    db: DBSession,
    current_user: OptionalCurrentUser,
) -> PostResponse:
    """
    获取文章详情

    增加文章的阅读量。
    """
    post_service = PostService(db)

    # 增加阅读量（异步，不阻塞响应）
    await post_service.increment_view_count(post_id)

    post = await post_service.get_post_by_id(post_id)

    return PostResponse.model_validate(post)


@router.get(
    "/slug/{slug}",
    response_model=PostResponse,
    summary="通过 Slug 获取文章",
    description="根据 URL Slug 获取文章详情。",
)
async def get_post_by_slug(
    slug: str,
    db: DBSession,
    current_user: OptionalCurrentUser,
) -> PostResponse:
    """
    通过 Slug 获取文章

    使用 SEO 友好的 URL slug 获取文章。
    """
    post_service = PostService(db)
    post = await post_service.get_post_by_slug(slug)

    return PostResponse.model_validate(post)


@router.patch(
    "/{post_id}",
    response_model=PostResponse,
    summary="更新文章",
    description="更新文章内容。只有作者或管理员可以更新。",
)
async def update_post(
    post_id: int,
    post_data: PostUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> PostResponse:
    """
    更新文章

    只有文章作者或管理员可以更新。
    """
    post_service = PostService(db)
    post = await post_service.update_post(post_id, post_data, current_user)

    return PostResponse.model_validate(post)


@router.delete(
    "/{post_id}",
    response_model=SuccessResponse,
    summary="删除文章",
    description="删除文章（软删除）。只有作者或管理员可以删除。",
)
async def delete_post(
    post_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> SuccessResponse:
    """
    删除文章

    执行软删除。只有文章作者或管理员可以删除。
    """
    post_service = PostService(db)
    await post_service.delete_post(post_id, current_user)

    return SuccessResponse(message="文章已删除")


@router.post(
    "/{post_id}/publish",
    response_model=PostResponse,
    summary="发布文章",
    description="将文章状态设置为已发布。只有作者或管理员可以发布。",
)
async def publish_post(
    post_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> PostResponse:
    """
    发布文章

    将文章从草稿状态发布为已发布状态。
    """
    post_service = PostService(db)
    post = await post_service.publish_post(post_id, current_user)

    return PostResponse.model_validate(post)


@router.post(
    "/{post_id}/archive",
    response_model=PostResponse,
    summary="归档文章",
    description="将文章状态设置为已归档。只有作者或管理员可以归档。",
)
async def archive_post(
    post_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> PostResponse:
    """
    归档文章

    将文章从已发布状态归档。
    """
    post_service = PostService(db)
    post = await post_service.archive_post(post_id, current_user)

    return PostResponse.model_validate(post)


@router.get(
    "/my/posts",
    response_model=PageResponse[PostListItem],
    summary="获取我的文章",
    description="获取当前用户的文章列表（包括所有状态）。",
)
async def get_my_posts(
    db: DBSession,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    status: PostStatus = Query(default=None, description="按状态筛选"),
) -> PageResponse[PostListItem]:
    """
    获取我的文章

    获取当前用户的所有文章，包括草稿。
    """
    post_service = PostService(db)
    posts, total = await post_service.get_user_posts(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        status=status,
    )

    items = [PostListItem.model_validate(post) for post in posts]
    meta = PageMeta.create(page=page, page_size=page_size, total_items=total)

    return PageResponse(items=items, meta=meta)
