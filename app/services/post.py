"""
文章服务模块

封装文章相关的业务逻辑。
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
import re

from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException, BadRequestException
from app.models.post import Post, PostStatus, PostVisibility
from app.models.user import User, UserRole
from app.schemas.post import PostCreate, PostUpdate


class PostService:
    """
    文章服务类

    处理所有文章相关的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_post(
        self,
        author_id: int,
        post_data: PostCreate,
    ) -> Post:
        """
        创建新文章

        自动生成 slug，设置作者和初始状态。
        """
        # 生成 slug
        slug = post_data.slug or self._generate_slug(post_data.title)

        # 检查 slug 唯一性
        if await self._slug_exists(slug):
            slug = f"{slug}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        # 创建文章
        post = Post(
            title=post_data.title,
            content=post_data.content,
            summary=post_data.summary,
            cover_image=post_data.cover_image,
            category=post_data.category,
            tags=post_data.tags,
            slug=slug,
            meta_description=post_data.meta_description,
            author_id=author_id,
            status=PostStatus.DRAFT,
            visibility=post_data.visibility,
        )

        self.db.add(post)
        await self.db.commit()
        await self.db.refresh(post)

        return post

    async def get_post_by_id(self, post_id: int, include_content: bool = True) -> Post:
        """
        根据 ID 获取文章

        包含作者信息。
        """
        query = (
            select(Post)
            .where(
                Post.id == post_id,
                Post.deleted_at.is_(None)
            )
            .options(selectinload(Post.author))
        )

        result = await self.db.execute(query)
        post = result.scalar_one_or_none()

        if not post:
            raise NotFoundException(resource="文章", resource_id=post_id)

        return post

    async def get_post_by_slug(self, slug: str) -> Post:
        """根据 slug 获取文章"""
        query = (
            select(Post)
            .where(
                Post.slug == slug,
                Post.deleted_at.is_(None)
            )
            .options(selectinload(Post.author))
        )

        result = await self.db.execute(query)
        post = result.scalar_one_or_none()

        if not post:
            raise NotFoundException(resource="文章", resource_id=slug)

        return post

    async def update_post(
        self,
        post_id: int,
        post_data: PostUpdate,
        current_user: Optional[User] = None,
    ) -> Post:
        """
        更新文章

        如果提供了 current_user，验证是否为作者或管理员。
        """
        post = await self.get_post_by_id(post_id)

        # 权限检查
        if current_user:
            if post.author_id != current_user.id and not current_user.is_admin:
                raise BadRequestException(detail="您没有权限编辑这篇文章")

        # 更新字段
        update_data = post_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(post, field, value)

        # 如果状态变为发布，设置发布时间
        if post_data.status == PostStatus.PUBLISHED and not post.published_at:
            post.published_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(post)

        return post

    async def delete_post(self, post_id: int, current_user: User) -> None:
        """
        删除文章

        只能删除自己的文章或管理员可删除任何文章。
        """
        post = await self.get_post_by_id(post_id)

        # 权限检查
        if post.author_id != current_user.id and not current_user.is_admin:
            raise BadRequestException(detail="您没有权限删除这篇文章")

        # 软删除
        post.deleted_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def publish_post(self, post_id: int, current_user: User) -> Post:
        """发布文章"""
        post = await self.get_post_by_id(post_id)

        # 权限检查
        if post.author_id != current_user.id and not current_user.is_admin:
            raise BadRequestException(detail="您没有权限发布这篇文章")

        post.status = PostStatus.PUBLISHED
        post.published_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(post)

        return post

    async def archive_post(self, post_id: int, current_user: User) -> Post:
        """归档文章"""
        post = await self.get_post_by_id(post_id)

        if post.author_id != current_user.id and not current_user.is_admin:
            raise BadRequestException(detail="您没有权限归档这篇文章")

        post.status = PostStatus.ARCHIVED

        await self.db.commit()
        await self.db.refresh(post)

        return post

    async def increment_view_count(self, post_id: int) -> None:
        """增加文章阅读量"""
        post = await self.get_post_by_id(post_id)
        post.view_count += 1
        await self.db.commit()

    async def get_posts_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        status: Optional[PostStatus] = None,
        author_id: Optional[int] = None,
        visibility: Optional[PostVisibility] = None,
        include_drafts: bool = False,
    ) -> Tuple[List[Post], int]:
        """
        分页获取文章列表

        支持多种筛选条件。
        """
        query = (
            select(Post)
            .where(Post.deleted_at.is_(None))
            .options(selectinload(Post.author))
        )

        # 应用过滤条件
        if keyword:
            keyword_filter = f"%{keyword}%"
            query = query.where(
                or_(
                    Post.title.ilike(keyword_filter),
                    Post.content.ilike(keyword_filter),
                    Post.summary.ilike(keyword_filter),
                )
            )

        if category:
            query = query.where(Post.category == category)

        if tag:
            query = query.where(Post.tags.ilike(f"%{tag}%"))

        if status:
            query = query.where(Post.status == status)

        if author_id:
            query = query.where(Post.author_id == author_id)

        if visibility:
            query = query.where(Post.visibility == visibility)

        # 默认不显示草稿（除非明确指定）
        if not include_drafts and status is None:
            query = query.where(Post.status == PostStatus.PUBLISHED)

        # 获取总数
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # 应用分页和排序
        query = query.order_by(Post.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        posts = result.scalars().all()

        return list(posts), total

    async def get_user_posts(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status: Optional[PostStatus] = None,
    ) -> Tuple[List[Post], int]:
        """
        获取用户的文章列表

        用于用户个人中心的文章管理。
        """
        return await self.get_posts_paginated(
            page=page,
            page_size=page_size,
            author_id=user_id,
            status=status,
            include_drafts=True,
        )

    async def _slug_exists(self, slug: str) -> bool:
        """检查 slug 是否已存在"""
        query = select(Post).where(
            Post.slug == slug,
            Post.deleted_at.is_(None)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    def _generate_slug(self, title: str) -> str:
        """
        从标题生成 slug

        转换为小写，替换空格和特殊字符。
        """
        # 转小写
        slug = title.lower()
        # 替换空格为连字符
        slug = re.sub(r'\s+', '-', slug)
        # 移除非字母数字字符
        slug = re.sub(r'[^a-z0-9\-]', '', slug)
        # 移除连续连字符
        slug = re.sub(r'-+', '-', slug)
        # 移除首尾连字符
        slug = slug.strip('-')

        return slug
