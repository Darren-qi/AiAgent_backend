"""Auth endpoint module"""

from fastapi import APIRouter, status, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession, CurrentUser
from app.schemas.user import UserCreate, UserResponse
from app.schemas.token import Token, TokenRefreshRequest
from app.schemas.common import SuccessResponse
from app.services.auth import AuthService
from app.services.user import UserService


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: DBSession) -> UserResponse:
    auth_service = AuthService(db)
    user, token = await auth_service.register(user_data)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token)
async def login(request: LoginRequest, db: DBSession) -> Token:
    auth_service = AuthService(db)
    user, token = await auth_service.login(request.username_or_email, request.password)
    return token


@router.post("/refresh", response_model=Token)
async def refresh_token(request: TokenRefreshRequest, db: DBSession) -> Token:
    auth_service = AuthService(db)
    return await auth_service.refresh_token(request.refresh_token)


@router.post("/logout", response_model=SuccessResponse)
async def logout(current_user: CurrentUser) -> SuccessResponse:
    return SuccessResponse(message="logged out successfully")


@router.post("/password-reset", response_model=SuccessResponse)
async def request_password_reset(email: str, db: DBSession) -> SuccessResponse:
    auth_service = AuthService(db)
    await auth_service.generate_password_reset_token(email)
    return SuccessResponse(message="reset link sent if email exists")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser,
    db: DBSession,
) -> UserResponse:
    user_service = UserService(db)
    user = await user_service.get_user_by_id(current_user["id"])
    return UserResponse.model_validate(user)
