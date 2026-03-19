"""
Token Schema 模块

定义与认证令牌相关的 Pydantic 模型。
"""

from pydantic import BaseModel, Field


class Token(BaseModel):
    """
    JWT 令牌响应

    登录成功后返回的令牌信息。
    """

    access_token: str = Field(description="访问令牌")
    refresh_token: str = Field(description="刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="访问令牌过期时间（秒）")


class TokenPayload(BaseModel):
    """
    JWT 令牌载荷

    解码后的令牌内容。
    """

    sub: str = Field(description="主题（通常是用户ID）")
    exp: int = Field(description="过期时间戳")
    type: str = Field(description="令牌类型（access 或 refresh）")
    iat: int = Field(description="签发时间戳")


class TokenRefreshRequest(BaseModel):
    """
    刷新令牌请求

    使用刷新令牌获取新的访问令牌。
    """

    refresh_token: str = Field(description="刷新令牌")


class TokenVerifyRequest(BaseModel):
    """
    验证令牌请求

    验证令牌是否有效。
    """

    token: str = Field(description="要验证的令牌")
