"""
自定义异常模块

定义应用中使用的所有自定义异常类，
并提供异常处理器将异常转换为标准化的 HTTP 响应。
"""

from typing import Any, Dict, Optional

from fastapi import HTTPException, status


class AppException(HTTPException):
    """
    应用基础异常类

    所有自定义异常的基类，继承自 HTTPException。
    提供统一的异常处理方式。
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: Optional[Dict[str, str]] = None,
        error_code: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            status_code: HTTP 状态码
            detail: 错误详情信息
            headers: 响应头
            error_code: 业务错误码（用于前端区分错误类型）
            extra: 额外数据（会在响应中包含）
        """
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        """将异常转换为字典格式"""
        result = {
            "error": self.detail,
            "status_code": self.status_code,
        }
        if self.error_code:
            result["error_code"] = self.error_code
        if self.extra:
            result["extra"] = self.extra
        return result


# =============================================
# 认证相关异常
# =============================================
class UnauthorizedException(AppException):
    """未授权异常（401）"""

    def __init__(self, detail: str = "认证失败，请重新登录", **kwargs):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="UNAUTHORIZED",
            **kwargs,
        )


class InvalidCredentialsException(AppException):
    """凭证无效异常（401）"""

    def __init__(self, detail: str = "用户名或密码错误"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="INVALID_CREDENTIALS",
        )


class TokenExpiredException(AppException):
    """令牌过期异常（401）"""

    def __init__(self, detail: str = "令牌已过期，请重新登录"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="TOKEN_EXPIRED",
        )


class InvalidTokenException(AppException):
    """无效令牌异常（401）"""

    def __init__(self, detail: str = "无效的令牌"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="INVALID_TOKEN",
        )


# =============================================
# 权限相关异常
# =============================================
class ForbiddenException(AppException):
    """禁止访问异常（403）"""

    def __init__(self, detail: str = "您没有权限执行此操作"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="FORBIDDEN",
        )


class InsufficientPermissionsException(AppException):
    """权限不足异常（403）"""

    def __init__(self, detail: str = "权限不足"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="INSUFFICIENT_PERMISSIONS",
        )


# =============================================
# 资源相关异常
# =============================================
class NotFoundException(AppException):
    """资源不存在异常（404）"""

    def __init__(self, resource: str = "资源", resource_id: Optional[Any] = None):
        detail = f"{resource}不存在"
        if resource_id:
            detail = f"{resource} (ID: {resource_id}) 不存在"

        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            error_code="NOT_FOUND",
            extra={"resource": resource, "resource_id": resource_id},
        )


class AlreadyExistsException(AppException):
    """资源已存在异常（409）"""

    def __init__(self, resource: str = "资源", identifier: Optional[str] = None):
        detail = f"{resource}已存在"
        if identifier:
            detail = f"{resource} '{identifier}' 已存在"

        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            error_code="ALREADY_EXISTS",
            extra={"resource": resource, "identifier": identifier},
        )


# =============================================
# 请求相关异常
# =============================================
class BadRequestException(AppException):
    """请求错误异常（400）"""

    def __init__(self, detail: str = "请求参数错误"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="BAD_REQUEST",
        )


class ValidationException(AppException):
    """数据验证异常（422）"""

    def __init__(self, detail: str = "数据验证失败", errors: Optional[Dict[str, Any]] = None):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
            error_code="VALIDATION_ERROR",
            extra={"validation_errors": errors} if errors else None,
        )


# =============================================
# 服务器相关异常
# =============================================
class InternalServerException(AppException):
    """内部服务器错误异常（500）"""

    def __init__(self, detail: str = "服务器内部错误"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code="INTERNAL_ERROR",
        )


class ServiceUnavailableException(AppException):
    """服务不可用异常（503）"""

    def __init__(self, detail: str = "服务暂时不可用", retry_after: Optional[int] = None):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            error_code="SERVICE_UNAVAILABLE",
            extra={"retry_after": retry_after} if retry_after else None,
        )


# =============================================
# 业务特定异常
# =============================================
class EmailAlreadyExistsException(AlreadyExistsException):
    """邮箱已注册异常"""

    def __init__(self, email: str):
        super().__init__(resource="邮箱", identifier=email)
        self.error_code = "EMAIL_ALREADY_EXISTS"


class UsernameAlreadyExistsException(AlreadyExistsException):
    """用户名已存在异常"""

    def __init__(self, username: str):
        super().__init__(resource="用户名", identifier=username)
        self.error_code = "USERNAME_ALREADY_EXISTS"


class UserInactiveException(AppException):
    """用户未激活异常"""

    def __init__(self, detail: str = "用户账户未激活，请先激活账户"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="USER_INACTIVE",
        )


class UserBannedException(AppException):
    """用户被禁用异常"""

    def __init__(self, detail: str = "用户账户已被禁用"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="USER_BANNED",
        )
