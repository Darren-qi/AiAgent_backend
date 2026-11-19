"""
Schemas 模块 __init__.py

导出所有 Pydantic Schema 模型。
"""

from app.schemas.common import (
    ErrorResponse,
    IDSchema,
    PageMeta,
    PageResponse,
    PaginationParams,
    ResponseWrapper,
    SoftDeleteSchema,
    SuccessResponse,
    TimestampSchema,
)
from app.schemas.post import (
    AuthorInfo,
    PostBase,
    PostCreate,
    PostListItem,
    PostPublish,
    PostQueryParams,
    PostResponse,
    PostStats,
    PostUpdate,
)
from app.schemas.token import (
    Token,
    TokenPayload,
    TokenRefreshRequest,
    TokenVerifyRequest,
)
from app.schemas.user import (
    UserAdminUpdate,
    UserBase,
    UserCreate,
    UserListResponse,
    UserPasswordUpdate,
    UserPublicProfile,
    UserQueryParams,
    UserResponse,
    UserStats,
    UserUpdate,
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
