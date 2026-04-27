### 1. 需求分析

## 功能清单
1. **项目分层架构** - 清晰的模块划分：API路由层、业务逻辑层、数据访问层、模型层
2. **常用工具集成** - 数据库(SQLAlchemy)、缓存(Redis)、日志、配置管理、认证鉴权、异常处理
3. **扩展性支持** - 依赖注入、中间件机制、插件化设计、环境配置分离
4. **开发体验优化** - 自动API文档、请求验证、CORS、健康检查

## 验收标准
- 用户可以运行项目并访问Swagger文档
- 用户可以配置数据库连接并执行CRUD操作
- 用户可以通过配置文件切换开发/生产环境
- 用户可以看到统一的错误响应和日志记录
- 用户可以通过健康检查接口确认服务状态

STAGE_DONE: requirements

### 2. 项目创建

```python
# 创建项目目录结构
project_dir = project_create()
```

### 3. 项目文件结构

```
fastapi_project/
├── app/
│   ├── __init__.py
│   ├── main.py                 # 应用入口
│   ├── config.py               # 配置管理
│   ├── dependencies.py         # 依赖注入
│   ├── exceptions.py           # 异常处理
│   ├── middleware.py            # 中间件
│   ├── api/
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py         # 认证接口
│   │   │   ├── users.py        # 用户接口
│   │   │   └── health.py       # 健康检查
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py         # 安全认证
│   │   └── logger.py           # 日志配置
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py             # 基础模型
│   │   └── user.py             # 用户模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user.py             # 用户Schema
│   │   └── common.py           # 通用Schema
│   ├── services/
│   │   ├── __init__.py
│   │   ├── user_service.py     # 用户服务
│   │   └── auth_service.py     # 认证服务
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py             # 基础仓储
│   │   └── user_repository.py  # 用户仓储
│   └── db/
│       ├── __init__.py
│       ├── session.py          # 数据库会话
│       └── base.py             # 数据库基类
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── test_api/
├── alembic/                    # 数据库迁移
├── .env.example
├── .gitignore
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### 4. 核心代码实现

```python
# 1. app/config.py - 配置管理
file_write(path="app/config.py", content="""
from pydantic_settings import BaseSettings
from typing import Optional
import os
from functools import lru_cache

class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "FastAPI Project"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    
    # 数据库配置
    DATABASE_URL: str = "sqlite:///./test.db"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    
    # Redis配置
    REDIS_URL: Optional[str] = None
    REDIS_PASSWORD: Optional[str] = None
    
    # JWT配置
    SECRET_KEY: str = "your-secret-key-here"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # CORS配置
    CORS_ORIGINS: list = ["*"]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list = ["*"]
    CORS_HEADERS: list = ["*"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def get_settings() -> Settings:
    return Settings()
""")

# 2. app/db/session.py - 数据库会话管理
file_write(path="app/db/session.py", content="""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    \"\"\"获取数据库会话的依赖注入\"\"\"
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
""")

# 3. app/db/base.py - 数据库基类
file_write(path="app/db/base.py", content="""
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
from typing import Optional

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    \"\"\"时间戳混入类\"\"\"
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
""")

# 4. app/models/base.py - 基础模型
file_write(path="app/models/base.py", content="""
from app.db.base import Base, TimestampMixin
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, Boolean
from typing import Optional

class BaseModel(Base, TimestampMixin):
    \"\"\"所有模型的基类\"\"\"
    __abstract__ = True
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
""")

# 5. app/models/user.py - 用户模型
file_write(path="app/models/user.py", content="""
from app.models.base import BaseModel
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime
from datetime import datetime
from typing import Optional

class User(BaseModel):
    __tablename__ = "users"
    
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
""")

# 6. app/schemas/common.py - 通用Schema
file_write(path="app/schemas/common.py", content="""
from pydantic import BaseModel
from typing import Generic, TypeVar, List, Optional

T = TypeVar('T')

class ResponseModel(BaseModel, Generic[T]):
    \"\"\"统一响应模型\"\"\"
    code: int = 200
    message: str = "success"
    data: Optional[T] = None

class PaginationModel(BaseModel, Generic[T]):
    \"\"\"分页模型\"\"\"
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int

class ErrorResponse(BaseModel):
    \"\"\"错误响应模型\"\"\"
    code: int
    message: str
    detail: Optional[str] = None
""")

# 7. app/schemas/user.py - 用户Schema
file_write(path="app/schemas/user.py", content="""
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional

class UserCreate(BaseModel):
    \"\"\"创建用户请求\"\"\"
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    full_name: Optional[str] = None

class UserUpdate(BaseModel):
    \"\"\"更新用户请求\"\"\"
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    \"\"\"用户响应\"\"\"
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    \"\"\"登录请求\"\"\"
    username: str
    password: str

class TokenResponse(BaseModel):
    \"\"\"令牌响应\"\"\"
    access_token: str
    token_type: str = "bearer"
    expires_in: int
""")

# 8. app/core/security.py - 安全认证
file_write(path="app/core/security.py", content="""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    \"\"\"验证密码\"\"\"
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    \"\"\"获取密码哈希\"\"\"
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    \"\"\"创建访问令牌\"\"\"
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_access_token(token: str) -> dict:
    \"\"\"解码访问令牌\"\"\"
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(token: str = Depends(oauth2_scheme)):
    \"\"\"获取当前用户\"\"\"
    payload = decode_access_token(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return username
""")

# 9. app/core/logger.py - 日志配置
file_write(path="app/core/logger.py", content="""
import logging
import sys
from app.config import get_settings

settings = get_settings()

def setup_logging() -> None:
    \"\"\"配置日志系统\"\"\"
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format=settings.LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("app.log")
        ]
    )
    
    # 设置第三方库的日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    \"\"\"获取日志器\"\"\"
    return logging.getLogger(name)
""")

# 10. app/exceptions.py - 异常处理
file_write(path="app/exceptions.py", content="""
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Any, Dict, Optional

class AppException(HTTPException):
    \"\"\"应用基础异常\"\"\"
    def __init__(
        self,
        status_code: int,
        message: str,
        detail: Optional[Any] = None,
        headers: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.message = message
        self.headers = headers

class NotFoundException(AppException):
    \"\"\"资源未找到异常\"\"\"
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=404, message="Not Found", detail=detail)

class ValidationException(AppException):
    \"\"\"验证异常\"\"\"
    def __init__(self, detail: str = "Validation error"):
        super().__init__(status_code=422, message="Validation Error", detail=detail)

class UnauthorizedException(AppException):
    \"\"\"未授权异常\"\"\"
    def __init__(self, detail: str = "Not authorized"):
        super().__init__(status_code=401, message="Unauthorized", detail=detail)

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    \"\"\"应用异常处理器\"\"\"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.message,
            "detail": exc.detail
        }
    )

async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    \"\"\"通用异常处理器\"\"\"
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "Internal Server Error",
            "detail": str(exc) if getattr(request.app, "debug", False) else None
        }
    )
""")

# 11. app/middleware.py - 中间件
file_write(path="app/middleware.py", content="""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logger import get_logger
import time
import uuid

logger = get_logger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    \"\"\"请求日志中间件\"\"\"
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        # 记录请求
        logger.info(f"Request {request_id}: {request.method} {request.url.path}")
        
        response = await call_next(request)
        
        # 记录响应
        process_time = time.time() - start_time
        logger.info(
            f"Response {request_id}: {response.status_code} "
            f"({process_time:.3f}s)"
        )
        
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(process_time)
        
        return response

class CORSMiddleware(BaseHTTPMiddleware):
    \"\"\"CORS中间件\"\"\"
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
""")

# 12. app/repositories/base.py - 基础仓储
file_write(path="app/repositories/base.py", content="""
from typing import Generic, TypeVar, Type, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, update, delete
from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)

class BaseRepository(Generic[ModelType]):
    \"\"\"基础仓储类，提供通用的CRUD操作\"\"\"
    
    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db = db
    
    def create(self, **kwargs) -> ModelType:
        \"\"\"创建记录\"\"\"
        instance = self.model(**kwargs)
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance
    
    def get(self, id: int) -> Optional[ModelType]:
        \"\"\"根据ID获取记录\"\"\"
        return self.db.get(self.model, id)
    
    def get_all(
        self, 
        skip: int = 0, 
        limit: int = 100,
        **filters
    ) -> List[ModelType]:
        \"\"\"获取所有记录（支持分页和过滤）\"\"\"
        query = select(self.model)
        
        for key, value in filters.items():
            if hasattr(self.model, key):
                query = query.where(getattr(self.model, key) == value)
        
        result = self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())
    
    def update(self, id: int, **kwargs) -> Optional[ModelType]:
        \"\"\"更新记录\"\"\"
        instance = self.get(id)
        if instance:
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            self.db.commit()
            self.db.refresh(instance)
        return instance
    
    def delete(self, id: int) -> bool:
        \"\"\"删除记录\"\"\"
        instance = self.get(id)
        if instance:
            self.db.delete(instance)
            self.db.commit()
            return True
        return False
    
    def count(self, **filters) -> int:
        \"\"\"统计记录数\"\"\"
        query = select(self.model)
        for key, value in filters.items():
            if hasattr(self.model, key):
                query = query.where(getattr(self.model, key) == value)
        return len(self.db.execute(query).scalars().all())
""")

# 13. app/repositories/user_repository.py - 用户仓储
file_write(path="app/repositories/user_repository.py", content="""
from app.repositories.base import BaseRepository
from app.models.user import User
from typing import Optional

class UserRepository(BaseRepository[User]):
    \"\"\"用户仓储\"\"\"
    
    def __init__(self, db):
        super().__init__(User, db)
    
    def get_by_username(self, username: str) -> Optional[User]:
        \"\"\"根据用户名获取用户\"\"\"
        return self.db.query(User).filter(User.username == username).first()
    
    def get_by_email(self, email: str) -> Optional[User]:
        \"\"\"根据邮箱获取用户\"\"\"
        return self.db.query(User).filter(User.email == email).first()
    
    def update_last_login(self, user_id: int) -> None:
        \"\"\"更新最后登录时间\"\"\"
        from datetime import datetime
        self.update(user_id, last_login=datetime.utcnow())
""")

# 14. app/services/user_service.py - 用户服务
file_write(path="app/services/user_service.py", content="""
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.core.security import get_password_hash, verify_password
from app.exceptions import NotFoundException, ValidationException
from typing import List, Optional

class UserService:
    \"\"\"用户服务层\"\"\"
    
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository
    
    def create_user(self, user_data: UserCreate) -> UserResponse:
        \"\"\"创建用户\"\"\"
        # 检查用户名是否已存在
        if self.user_repository.get_by_username(user_data.username):
            raise ValidationException(f"Username {user_data.username} already exists")
        
        # 检查邮箱是否已存在
        if self.user_repository.get_by_email(user_data.email):
            raise ValidationException(f"Email {user_data.email} already exists")
        
        # 创建用户
        user = self.user_repository.create(
            username=user_data.username,
            email=user_data.email,
            hashed_password=get_password_hash(user_data.password),
            full_name=user_data.full_name
        )
        
        return UserResponse.model_validate(user)
    
    def get_user(self, user_id: int) -> UserResponse:
        \"\"\"获取用户\"\"\"
        user = self.user_repository.get(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        return UserResponse.model_validate(user)
    
    def get_users(self, skip: int = 0, limit: int = 100) -> List[UserResponse]:
        \"\"\"获取用户列表\"\"\"
        users = self.user_repository.get_all(skip=skip, limit=limit)
        return [UserResponse.model_validate(user) for user in users]
    
    def update_user(self, user_id: int, user_data: UserUpdate) -> UserResponse:
        \"\"\"更新用户\"\"\"
        user = self.user_repository.get(user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        
        update_data = user_data.model_dump(exclude_unset=True)
        updated_user = self.user_repository.update(user_id, **update_data)
        return UserResponse.model_validate(updated_user)
    
    def delete_user(self, user_id: int) -> bool:
        \"\"\"删除用户\"\"\"
        if not self.user_repository.get(user_id):
            raise NotFoundException(f"User {user_id} not found")
        return self.user_repository.delete(user_id)
    
    def authenticate(self, username: str, password: str) -> Optional[UserResponse]:
        \"\"\"用户认证\"\"\"
        user = self.user_repository.get_by_username(username)
        if not user:
            return None
        
        if not verify_password(password, user.hashed_password):
            return None
        
        self.user_repository.update_last_login(user.id)
        return UserResponse.model_validate(user)
""")

# 15. app/services/auth_service.py - 认证服务
file_write(path="app/services/auth_service.py", content="""
from app.core.security import create_access_token, decode_access_token
from app.schemas.user import TokenResponse, LoginRequest
from app.services.user_service import UserService
from app.exceptions import UnauthorizedException
from datetime import timedelta

class AuthService:
    \"\"\"认证服务\"\"\"
    
    def __init__(self, user_service: UserService):
        self.user_service = user_service
    
    def login(self, login_data: LoginRequest) -> TokenResponse:
        \"\"\"用户登录\"\"\"
        user = self.user_service.authenticate(
            login_data.username, 
            login_data.password
        )
        
        if not user:
            raise UnauthorizedException("Invalid username or password")
        
        # 创建访问令牌
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id},
            expires_delta=timedelta(minutes=30)
        )
        
        return TokenResponse(
            access_token=access_token,
            expires_in=1800
        )
    
    def verify_token(self, token: str) -> dict:
        \"\"\"验证令牌\"\"\"
        return decode_access_token(token)
""")

# 16. app/dependencies.py - 依赖注入
file_write(path="app/dependencies.py", content="""
from fastapi import Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService
from app.services.auth_service import AuthService

def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    \"\"\"获取用户仓储\"\"\"
    return UserRepository(db)

def get_user_service(
    user_repository: UserRepository = Depends(get_user_repository)
) -> UserService:
    \"\"\"获取用户服务\"\"\"
    return UserService(user_repository)

def get_auth_service(
    user_service: UserService = Depends(get_user_service)
) -> AuthService:
    \"\"\"获取认证服务\"\"\"
    return AuthService(user_service)
""")

# 17. app/api/v1/health.py - 健康检查
file_write(path="app/api/v1/health.py", content="""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import ResponseModel

router = APIRouter(tags=["health"])

@router.get("/health", response_model=ResponseModel)
async def health_check(db: Session = Depends(get_db)):
    \"\"\"健康检查接口\"\"\"
    try:
        # 检查数据库连接
        db.execute("SELECT 1")
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"
    
    return ResponseModel(
        code=200,
        message="OK",
        data={
            "status": "healthy",
            "database": db_status,
            "version": "1.0.0"
        }
    )
""")

# 18. app/api/v1/auth.py - 认证接口
file_write(path="app/api/v1/auth.py", content="""
from fastapi import APIRouter, Depends
from app.schemas.user import LoginRequest, TokenResponse
from app.schemas.common import ResponseModel
from app.services.auth_service import AuthService
from app.dependencies import get_auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])

@router.post("/login", response_model=ResponseModel[TokenResponse])
async def login(
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    \"\"\"用户登录\"\"\"
    token = auth_service.login(login_data)
    return ResponseModel(data=token)

@router.post("/verify", response_model=ResponseModel)
async def verify_token(
    token: str,
    auth_service: AuthService = Depends(get_auth_service)
):
    \"\"\"验证令牌\"\"\"
    payload = auth_service.verify_token(token)
    return ResponseModel(data=payload)
""")

# 19. app/api/v1/users.py - 用户接口
file_write(path="app/api/v1/users.py", content="""
from fastapi import APIRouter, Depends, Query
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.schemas.common import ResponseModel, PaginationModel
from app.services.user_service import UserService
from app.dependencies import get_user_service
from typing import List

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/", response_model=ResponseModel[UserResponse], status_code=201)
async def create_user(
    user_data: UserCreate,
    user_service: UserService = Depends(get_user_service)
):
    \"\"\"创建用户\"\"\"
    user = user_service.create_user(user_data)
    return ResponseModel(data=user)

@router.get("/{user_id}", response_model=ResponseModel[UserResponse])
async def get_user(
    user_id: int,
    user_service: UserService = Depends(get_user_service)
):
    \"\"\"获取用户详情\"\"\"
    user = user_service.get_user(user_id)
    return ResponseModel(data=user)

@router.get("/", response_model=ResponseModel[PaginationModel[UserResponse]])
async def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user_service: UserService = Depends(get_user_service)
):
    \"\"\"获取用户列表（分页）\"\"\"
    users = user_service.get_users(skip=skip, limit=limit)
    return ResponseModel(
        data=PaginationModel(
            items=users,
            total=len(users),
            page=skip // limit + 1,
            page_size=limit,
            total_pages=(len(users) + limit - 1) // limit
        )
    )

@router.put("/{user_id}", response_model=ResponseModel[UserResponse])
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    user_service: UserService = Depends(get_user_service)
):
    \"\"\"更新用户\"\"\"
    user = user_service.update_user(user_id, user_data)
    return ResponseModel(data=user)

@router.delete("/{user_id}", response_model=ResponseModel)
async def delete_user(
    user_id: int,
    user_service: UserService = Depends(get_user_service)
):
    \"\"\"删除用户\"\"\"
    user_service.delete_user(user_id)
    return ResponseModel(message="User deleted successfully")
""")

# 20. app/main.py - 应用入口
file_write(path="app/main.py", content="""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import health, auth, users
from app.exceptions import AppException, app_exception_handler, generic_exception_handler
from app.middleware import RequestLoggingMiddleware
from app.core.logger import setup_logging, get_logger
from app.config import get_settings
from app.db.base import Base
from app.db.session import engine

# 设置日志
setup_logging()
logger = get_logger(__name__)

# 获取配置
settings = get_settings()

# 创建应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="A production-ready FastAPI project template",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)

# 添加请求日志中间件
app.add_middleware(RequestLoggingMiddleware)

# 注册异常处理器
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 注册路由
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)

@app.on_event("startup")
async def startup():
    \"\"\"应用启动时执行\"\"\"
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    
    # 创建数据库表
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")

@app.on_event("shutdown")
async def shutdown():
    \"\"\"应用关闭时执行\"\"\"
    logger.info(f"Shutting down {settings.APP_NAME}")
""")

# 21. 配置文件
file_write(path=".env.example", content="""
# 应用配置
APP_NAME=FastAPI Project
APP_VERSION=1.0.0
DEBUG=false

# 数据库配置
DATABASE_URL=sqlite:///./test.db
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# Redis配置
REDIS_URL=
REDIS_PASSWORD=

# JWT配置
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 日志配置
LOG_LEVEL=INFO
""")

file_write(path=".gitignore", content="""
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg-info/
dist/
build/

# Environment
.env
.venv/
venv/
env/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Database
*.db
*.sqlite

# Logs
*.log

# Docker
.docker/

# Testing
.coverage
htmlcov/
.pytest_cache/
""")

file_write(path="requirements.txt", content="""
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
pydantic==2.5.2
pydantic-settings==2.1.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6
alembic==1.13.0
redis==5.0.1
httpx==0.25.2
pytest==7.4.3
pytest-asyncio==0.23.2
httptools==0.6.1
""")

file_write(path="Dockerfile", content="""
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
""")

file_write(path="docker-compose.yml", content="""
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/fastapi
      - REDIS_URL=redis://redis:6379
      - SECRET_KEY=${SECRET_KEY:-your-secret-key}
      - DEBUG=true
    volumes:
      - .:/app
    depends_on:
      - db
      - redis
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=fastapi
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
""")

# 22. 测试配置
file_write(path="tests/__init__.py", content="")
file_write(path="tests/conftest.py", content="""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app