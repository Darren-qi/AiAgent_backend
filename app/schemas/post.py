"""
文章 Schema 模块

定义与文章相关的 Pydantic 模型。
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.post import PostStatus, PostVisibility


# =============================================
# 文章 Schema
# =============================================

class PostBase(BaseModel):
    """文章基础 Schema"""
    title: Optional[str] = Field(default=None, max_length=255, description="标题")
    content: Optional[str] = Field(default=None, description="内容")
    summary: Optional[str] = Field(default=None, description="摘要")
    cover_image: Optional[str] = Field(default=None, max_length=500, description="封面图片")
    category: Optional[str] = Field(default=None, max_length=50, description="分类")
    tags: Optional[str] = Field(default=None, max_length=255, description="标签（逗号分隔）")
    visibility: PostVisibility = Field(default=PostVisibility.PUBLIC, description="可见性")


class PostCreate(PostBase):
    """
    文章创建 Schema

    用于创建新文章。
    """

    title: str = Field(min_length=1, max_length=255, description="标题")
    content: str = Field(min_length=1, description="内容")
    category: Optional[str] = Field(default=None, max_length=50, description="分类")
    tags: Optional[str] = Field(default=None, max_length=255, description="标签")
    slug: Optional[str] = Field(default=None, max_length=255, description="URL Slug")
    meta_description: Optional[str] = Field(default=None, max_length=160, description="SEO描述")

    @field_validator("slug", mode="before")
    @classmethod
    def generate_slug(cls, v: Optional[str], info) -> str:
        """如果未提供 slug，从标题自动生成"""
        if v:
            return v.lower().replace(" ", "-")
        # 从其他字段获取标题并生成 slug
        return ""


class PostUpdate(BaseModel):
    """
    文章更新 Schema

    用于更新文章（部分更新）。
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=255, description="标题")
    content: Optional[str] = Field(default=None, min_length=1, description="内容")
    summary: Optional[str] = Field(default=None, description="摘要")
    cover_image: Optional[str] = Field(default=None, max_length=500, description="封面图片")
    category: Optional[str] = Field(default=None, max_length=50, description="分类")
    tags: Optional[str] = Field(default=None, max_length=255, description="标签")
    status: Optional[PostStatus] = Field(default=None, description="状态")
    visibility: Optional[PostVisibility] = Field(default=None, description="可见性")
    slug: Optional[str] = Field(default=None, max_length=255, description="URL Slug")
    meta_description: Optional[str] = Field(default=None, max_length=160, description="SEO描述")


class PostPublish(BaseModel):
    """发布文章 Schema"""
    status: PostStatus = Field(default=PostStatus.PUBLISHED, description="发布状态")


# =============================================
# 文章响应 Schema
# =============================================

class AuthorInfo(BaseModel):
    """作者信息（嵌套在文章中）"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="作者ID")
    username: str = Field(description="用户名")
    nickname: Optional[str] = Field(default=None, description="昵称")
    avatar: Optional[str] = Field(default=None, description="头像")


class PostResponse(BaseModel):
    """
    文章响应 Schema

    返回给客户端的文章详情。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="文章ID")
    title: str = Field(description="标题")
    content: str = Field(description="内容")
    summary: Optional[str] = Field(default=None, description="摘要")
    cover_image: Optional[str] = Field(default=None, description="封面图片")
    slug: str = Field(description="URL Slug")
    category: Optional[str] = Field(default=None, description="分类")
    tags: Optional[str] = Field(default=None, description="标签")
    status: PostStatus = Field(description="状态")
    visibility: PostVisibility = Field(description="可见性")
    view_count: int = Field(description="阅读量")
    like_count: int = Field(description="点赞数")
    comment_count: int = Field(description="评论数")
    meta_description: Optional[str] = Field(default=None, description="SEO描述")
    author: AuthorInfo = Field(description="作者信息")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")
    published_at: Optional[datetime] = Field(default=None, description="发布时间")


class PostListItem(BaseModel):
    """
    文章列表项 Schema

    用于文章列表展示（不包含完整内容）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="文章ID")
    title: str = Field(description="标题")
    summary: Optional[str] = Field(default=None, description="摘要")
    cover_image: Optional[str] = Field(default=None, description="封面图片")
    slug: str = Field(description="URL Slug")
    category: Optional[str] = Field(default=None, description="分类")
    status: PostStatus = Field(description="状态")
    view_count: int = Field(description="阅读量")
    like_count: int = Field(description="点赞数")
    author: AuthorInfo = Field(description="作者信息")
    created_at: datetime = Field(description="创建时间")
    published_at: Optional[datetime] = Field(default=None, description="发布时间")


class PostStats(BaseModel):
    """文章统计 Schema"""
    total_views: int = Field(description="总阅读量")
    total_likes: int = Field(description="总点赞数")
    total_comments: int = Field(description="总评论数")


# =============================================
# 查询参数 Schema
# =============================================

class PostQueryParams(BaseModel):
    """文章查询参数 Schema"""
    keyword: Optional[str] = Field(default=None, description="搜索关键词")
    category: Optional[str] = Field(default=None, description="按分类筛选")
    tag: Optional[str] = Field(default=None, description="按标签筛选")
    status: Optional[PostStatus] = Field(default=None, description="按状态筛选")
    author_id: Optional[int] = Field(default=None, description="按作者筛选")
    visibility: Optional[PostVisibility] = Field(default=None, description="按可见性筛选")
