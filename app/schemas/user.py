"""
用户 Schema 模块

定义与用户相关的 Pydantic 模型，包括：
- 用户创建/更新/响应 Schema
- 用户列表查询参数
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole, UserStatus


# =============================================
# 用户基础 Schema
# =============================================

class UserBase(BaseModel):
    """用户基础 Schema"""
    username: Optional[str] = Field(default=None, max_length=50, description="用户名")
    email: Optional[EmailStr] = Field(default=None, description="邮箱")
    nickname: Optional[str] = Field(default=None, max_length=100, description="昵称")
    bio: Optional[str] = Field(default=None, max_length=500, description="个人简介")


class UserCreate(UserBase):
    """
    用户创建 Schema

    用于注册新用户。
    """

    username: str = Field(min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(description="邮箱")
    password: str = Field(min_length=8, max_length=128, description="密码")
    nickname: Optional[str] = Field(default=None, max_length=100, description="昵称")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """验证用户名格式"""
        if not v.isalnum() and "_" not in v:
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """验证密码强度"""
        if len(v) < 8:
            raise ValueError("密码至少8个字符")
        return v


class UserUpdate(BaseModel):
    """
    用户更新 Schema

    用于更新用户信息（部分更新）。
    """

    nickname: Optional[str] = Field(default=None, max_length=100, description="昵称")
    avatar: Optional[str] = Field(default=None, max_length=500, description="头像URL")
    bio: Optional[str] = Field(default=None, max_length=500, description="个人简介")


class UserPasswordUpdate(BaseModel):
    """用户密码更新 Schema"""
    old_password: str = Field(description="旧密码")
    new_password: str = Field(min_length=8, max_length=128, description="新密码")

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        """验证新密码强度"""
        if len(v) < 8:
            raise ValueError("密码至少8个字符")
        return v


# =============================================
# 用户响应 Schema
# =============================================

class UserResponse(BaseModel):
    """
    用户响应 Schema

    返回给客户端的用户信息（不包含敏感字段）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    email: str = Field(description="邮箱")
    nickname: Optional[str] = Field(default=None, description="昵称")
    avatar: Optional[str] = Field(default=None, description="头像URL")
    bio: Optional[str] = Field(default=None, description="个人简介")
    role: UserRole = Field(description="用户角色")
    status: UserStatus = Field(description="用户状态")
    is_active: bool = Field(description="是否激活")
    created_at: datetime = Field(description="注册时间")
    last_login_at: Optional[datetime] = Field(default=None, description="最后登录时间")


class UserListResponse(BaseModel):
    """用户列表响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: Optional[str] = Field(default=None, description="昵称")
    avatar: Optional[str] = Field(default=None, description="头像URL")
    role: UserRole = Field(description="用户角色")
    status: UserStatus = Field(description="用户状态")
    created_at: datetime = Field(description="注册时间")


class UserPublicProfile(BaseModel):
    """
    用户公开资料 Schema

    公开可见的用户信息。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: Optional[str] = Field(default=None, description="昵称")
    avatar: Optional[str] = Field(default=None, description="头像URL")
    bio: Optional[str] = Field(default=None, description="个人简介")
    created_at: datetime = Field(description="注册时间")


# =============================================
# 用户管理 Schema（管理员使用）
# =============================================

class UserAdminUpdate(BaseModel):
    """
    管理员更新用户 Schema

    管理员可以修改用户的角色和状态。
    """

    role: Optional[UserRole] = Field(default=None, description="用户角色")
    status: Optional[UserStatus] = Field(default=None, description="用户状态")
    nickname: Optional[str] = Field(default=None, max_length=100, description="昵称")


class UserStats(BaseModel):
    """用户统计信息 Schema"""
    total_posts: int = Field(default=0, description="文章总数")
    published_posts: int = Field(default=0, description="已发布文章数")
    total_views: int = Field(default=0, description="总阅读量")


# =============================================
# 查询参数 Schema
# =============================================

class UserQueryParams(BaseModel):
    """用户查询参数 Schema"""
    keyword: Optional[str] = Field(default=None, description="搜索关键词（用户名/邮箱/昵称）")
    role: Optional[UserRole] = Field(default=None, description="按角色筛选")
    status: Optional[UserStatus] = Field(default=None, description="按状态筛选")
    is_active: Optional[bool] = Field(default=None, description="按激活状态筛选")
