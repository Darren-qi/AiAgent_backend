第一批：创建项目目录结构和核心配置文件。

```python
# 创建项目目录
project_create("fastapi_project")

# 创建项目依赖文件
file_write(path="requirements.txt", content="""fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.2
""")

# 创建应用入口文件
file_write(path="app/__init__.py", content="""# FastAPI应用包
""")

# 创建子模块初始化文件
file_write(path="app/routers/__init__.py", content="""# 路由模块
""")

file_write(path="app/schemas/__init__.py", content="""# 数据校验模块
""")

file_write(path="app/models/__init__.py", content="""# 数据模型模块
""")

file_write(path="app/services/__init__.py", content="""# 业务逻辑模块
""")
```

第二批：创建核心业务文件。

```python
# 创建Pydantic schema
file_write(path="app/schemas/user.py", content="""from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    \"\"\"创建用户请求模型\"\"\"
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    email: str = Field(..., description="邮箱地址")
    full_name: Optional[str] = Field(None, max_length=100, description="全名")

class UserUpdate(BaseModel):
    \"\"\"更新用户请求模型\"\"\"
    username: Optional[str] = Field(None, min_length=2, max_length=50)
    email: Optional[str] = Field(None)
    full_name: Optional[str] = Field(None, max_length=100)

class UserResponse(BaseModel):
    \"\"\"用户响应模型\"\"\"
    id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    email: str = Field(..., description="邮箱地址")
    full_name: Optional[str] = Field(None, description="全名")
    created_at: datetime = Field(..., description="创建时间")
    is_active: bool = Field(True, description="是否激活")

    class Config:
        from_attributes = True
""")

# 创建数据模型
file_write(path="app/models/user.py", content="""from datetime import datetime
from typing import Optional, Dict, Any

class User:
    \"\"\"用户数据模型（内存存储）\"\"\"
    
    def __init__(self, user_id: int, username: str, email: str, full_name: Optional[str] = None):
        self.id = user_id
        self.username = username
        self.email = email
        self.full_name = full_name
        self.created_at = datetime.now()
        self.is_active = True
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        \"\"\"转换为字典\"\"\"
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "created_at": self.created_at,
            "is_active": self.is_active,
            "updated_at": self.updated_at
        }

    def update(self, data: Dict[str, Any]) -> None:
        \"\"\"更新用户信息\"\"\"
        for key, value in data.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        self.updated_at = datetime.now()

    def deactivate(self) -> None:
        \"\"\"停用用户\"\"\"
        self.is_active = False
        self.updated_at = datetime.now()
""")

# 创建业务逻辑层
file_write(path="app/services/user_service.py", content="""from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models.user import User

class UserService:
    \"\"\"用户业务逻辑层\"\"\"
    
    def __init__(self):
        # 内存存储，key为用户ID，value为用户对象
        self._users: Dict[int, User] = {}
        self._next_id: int = 1
        
        # 初始化示例数据
        self._init_sample_data()

    def _init_sample_data(self) -> None:
        \"\"\"初始化示例数据\"\"\"
        sample_users = [
            {"username": "alice", "email": "alice@example.com", "full_name": "Alice Wang"},
            {"username": "bob", "email": "bob@example.com", "full_name": "Bob Li"},
            {"username": "charlie", "email": "charlie@example.com", "full_name": "Charlie Zhang"}
        ]
        for user_data in sample_users:
            self.create_user(user_data)

    def create_user(self, user_data: Dict[str, Any]) -> User:
        \"\"\"创建新用户\"\"\"
        user = User(
            user_id=self._next_id,
            username=user_data["username"],
            email=user_data["email"],
            full_name=user_data.get("full_name")
        )
        self._users[user.id] = user
        self._next_id += 1
        return user

    def get_user(self, user_id: int) -> Optional[User]:
        \"\"\"根据ID获取用户\"\"\"
        return self._users.get(user_id)

    def get_all_users(self) -> List[User]:
        \"\"\"获取所有活跃用户\"\"\"
        return [user for user in self._users.values() if user.is_active]

    def update_user(self, user_id: int, update_data: Dict[str, Any]) -> Optional[User]:
        \"\"\"更新用户信息\"\"\"
        user = self._users.get(user_id)
        if user and user.is_active:
            user.update(update_data)
            return user
        return None

    def delete_user(self, user_id: int) -> bool:
        \"\"\"软删除用户\"\"\"
        user = self._users.get(user_id)
        if user and user.is_active:
            user.deactivate()
            return True
        return False

    def get_user_count(self) -> int:
        \"\"\"获取活跃用户数量\"\"\"
        return len(self.get_all_users())

# 创建全局单例
user_service = UserService()
""")

# 创建路由处理器
file_write(path="app/routers/users.py", content="""from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.services.user_service import user_service

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={
        404: {"description": "用户不存在"},
        400: {"description": "请求参数错误"}
    }
)

@router.get("/", response_model=List[UserResponse], summary="获取所有用户")
async def get_users(
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(10, ge=1, le=100, description="返回记录数")
):
    \"\"\"
    获取所有活跃用户列表，支持分页
    
    - **skip**: 跳过的记录数（默认0）
    - **limit**: 返回的记录数（默认10，最大100）
    \"\"\"
    users = user_service.get_all_users()
    return users[skip:skip + limit]

@router.get("/count", response_model=dict, summary="获取用户总数")
async def get_user_count():
    \"\"\"获取当前活跃用户总数\"\"\"
    count = user_service.get_user_count()
    return {"total_users": count}

@router.get("/{user_id}", response_model=UserResponse, summary="获取指定用户")
async def get_user(user_id: int):
    \"\"\"
    根据用户ID获取用户详情
    
    - **user_id**: 用户ID（正整数）
    \"\"\"
    user = user_service.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户ID {user_id} 不存在"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户ID {user_id} 已被删除"
        )
    return user

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="创建新用户")
async def create_user(user_data: UserCreate):
    \"\"\"
    创建新用户
    
    - **username**: 用户名（必填，2-50字符）
    - **email**: 邮箱地址（必填）
    - **full_name**: 全名（可选）
    \"\"\"
    # 检查用户名是否已存在
    existing_users = user_service.get_all_users()
    for user in existing_users:
        if user.username == user_data.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"用户名 '{user_data.username}' 已存在"
            )
        if user.email == user_data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"邮箱 '{user_data.email}' 已被注册"
            )
    
    user = user_service.create_user(user_data.model_dump())
    return user

@router.put("/{user_id}", response_model=UserResponse, summary="更新用户信息")
async def update_user(user_id: int, update_data: UserUpdate):
    \"\"\"
    更新指定用户的信息
    
    - **user_id**: 用户ID
    - 支持部分更新，只传递需要修改的字段
    \"\"\"
    user = user_service.update_user(user_id, update_data.model_dump(exclude_none=True))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户ID {user_id} 不存在或已被删除"
        )
    return user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除用户")
async def delete_user(user_id: int):
    \"\"\"
    软删除指定用户（标记为未激活）
    
    - **user_id**: 用户ID
    \"\"\"
    success = user_service.delete_user(user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户ID {user_id} 不存在或已被删除"
        )
    return None
""")

# 创建主应用入口
file_write(path="app/main.py", content="""from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import users

# 创建FastAPI应用实例
app = FastAPI(
    title="FastAPI项目框架",
    description="基于FastAPI的现代化Web API框架，支持异步操作、自动API文档",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(users.router)

@app.get("/", tags=["系统"], summary="根路径")
async def root():
    \"\"\"API根路径，返回基础信息\"\"\"
    return {
        "service": "FastAPI项目框架",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }

@app.get("/health", tags=["系统"], summary="健康检查")
async def health_check():
    \"\"\"服务健康检查接口，返回服务运行状态\"\"\"
    return {
        "status": "ok",
        "version": "1.0.0",
        "service": "FastAPI项目框架"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
""")
```

第三批：创建启动脚本和配置文件。

```python
# 创建启动脚本
file_write(path="run.py", content="""#!/usr/bin/env python3
\"\"\"
FastAPI项目启动脚本
使用: python run.py
\"\"\"
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
""")

# 创建README文档
file_write(path="README.md", content="""# FastAPI项目框架

基于FastAPI的现代化Web API框架，支持异步操作、自动API文档。

## 技术栈

- **框架**: FastAPI
- **运行**: Uvicorn
- **数据验证**: Pydantic v2
- **数据存储**: 内存字典（预留SQLAlchemy集成位置）

## 项目结构

```
fastapi_project/
├── app/
│   ├── __init__.py
│   ├── main.py              # 应用入口
│   ├── routers/
│   │   ├── __init__.py
│   │   └── users.py         # 用户路由
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── user.py          # Pydantic模型
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py          # 数据模型
│   └── services/
│       ├── __init__.py
│       └── user_service.py  # 业务逻辑
├── requirements.txt
├── run.py
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 方式一：使用启动脚本
python run.py

# 方式二：直接使用uvicorn
uvicorn app.main:app --reload
```

### 3. 访问API

- API文档（Swagger）: http://localhost:8000/docs
- API文档（ReDoc）: http://localhost:8000/redoc
- 健康检查: http://localhost:8000/health

## API接口

### 用户管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /users/ | 获取用户列表 |
| GET | /users/count | 获取用户总数 |
| GET | /users/{id} | 获取指定用户 |
| POST | /users/ | 创建新用户 |
| PUT | /users/{id} | 更新用户信息 |
| DELETE | /users/{id} | 删除用户 |

## 架构说明

- **routers/**: API路由层，处理HTTP请求和响应
- **schemas/**: Pydantic模型层，负责请求/响应数据校验
- **models/**: 数据模型层，定义数据结构和业务方法
- **services/**: 业务逻辑层，封装核心业务操作
""")
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'fastapi_project'
📄 创建文件 'requirements.txt'
📄 创建文件 'app/__init__.py'
📄 创建文件 'app/routers/__init__.py'
📄 创建文件 'app/schemas/__init__.py'
📄 创建文件 'app/models/__init__.py'
📄 创建文件 'app/services/__init__.py'
📄 创建文件 'app/schemas/user.py'
📄 创建文件 'app/models/user.py'
📄 创建文件 'app/services/user_service.py'
📄 创建文件 'app/routers/users.py'
📄 创建文件 'app/main.py'
📄 创建文件 'run.py'
📄 创建文件 'README.md'