"""
Schemas 模块 __init__.py

导出所有 Pydantic Schema 模型。
"""

from app.schemas.common import (
    PaginationParams,
    PageMeta,
    PageResponse,
    ResponseWrapper,
    SuccessResponse,
    ErrorResponse,
    IDSchema,
    TimestampSchema,
    SoftDeleteSchema,
)
from app.schemas.token import (
    Token,
    TokenPayload,
    TokenRefreshRequest,
    TokenVerifyRequest,
)
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserUpdate,
    UserPasswordUpdate,
    UserResponse,
    UserListResponse,
    UserPublicProfile,
    UserAdminUpdate,
    UserStats,
    UserQueryParams,
)
from app.schemas.post import (
    PostBase,
    PostCreate,
    PostUpdate,
    PostPublish,
    PostResponse,
    PostListItem,
    AuthorInfo,
    PostStats,
    PostQueryParams,
)

__all__ = [
    # Common
    "PaginationParams",
    "PageMeta",
    "PageResponse",
    "ResponseWrapper",
    "SuccessResponse",
    "ErrorResponse",
    "IDSchema",
    "TimestampSchema",
    "SoftDeleteSchema",
    # Token
    "Token",
    "TokenPayload",
    "TokenRefreshRequest",
    "TokenVerifyRequest",
    # User
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserPasswordUpdate",
    "UserResponse",
    "UserListResponse",
    "UserPublicProfile",
    "UserAdminUpdate",
    "UserStats",
    "UserQueryParams",
    # Post
    "PostBase",
    "PostCreate",
    "PostUpdate",
    "PostPublish",
    "PostResponse",
    "PostListItem",
    "AuthorInfo",
    "PostStats",
    "PostQueryParams",
]
