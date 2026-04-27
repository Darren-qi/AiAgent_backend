### 第一批：项目目录、配置文件、入口文件

```
project_create("fastapi_project")
```

```
file_write(path="requirements.txt", content="""fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy[asyncio]==2.0.23
aiomysql==0.2.0
pymysql==1.1.0
pydantic-settings==2.1.0
python-dotenv==1.0.0
asyncio==3.4.3
""")
```

```
file_write(path=".env", content="""# MySQL 配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=root
MYSQL_DATABASE=fastapi_db

# Doris 配置
DORIS_HOST=localhost
DORIS_PORT=9030
DORIS_USER=root
DORIS_PASSWORD=
DORIS_DATABASE=doris_db
""")
```

```
file_write(path="app/__init__.py", content="""# FastAPI Project - Application Package
""")
```

```
file_write(path="app/core/__init__.py", content="""# Core Configuration Package
""")
```

```
file_write(path="app/core/config.py", content="""from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "FastAPI Project"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # MySQL 配置
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "root"
    MYSQL_DATABASE: str = "fastapi_db"

    # Doris 配置
    DORIS_HOST: str = "localhost"
    DORIS_PORT: int = 9030
    DORIS_USER: str = "root"
    DORIS_PASSWORD: str = ""
    DORIS_DATABASE: str = "doris_db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
""")
```

```
file_write(path="app/core/database.py", content="""from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

# 构建 MySQL 异步连接 URL
MYSQL_URL = f"mysql+aiomysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}?charset=utf8mb4"

# 创建异步引擎
async_engine = create_async_engine(
    MYSQL_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db() -> AsyncSession:
    \"\"\"获取数据库会话的依赖注入\"\"\"
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    \"\"\"初始化数据库连接（可在此处创建表）\"\"\"
    # 这里可以导入 models 并执行 Base.metadata.create_all
    pass

async def close_db():
    \"\"\"关闭数据库连接\"\"\"
    await async_engine.dispose()
""")
```

```
file_write(path="app/db/__init__.py", content="""# Database Utilities Package
from app.db.mysql import MySQLClient
from app.db.doris import DorisClient

__all__ = ["MySQLClient", "DorisClient"]
""")
```

```
file_write(path="app/db/mysql.py", content="""from typing import Any, Dict, List, Optional, Union
from sqlalchemy import text, select, insert, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal

class MySQLClient:
    \"\"\"
    MySQL 数据库操作工具类
    基于 SQLAlchemy 异步会话，提供通用的 CRUD 操作方法
    \"\"\"

    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session

    async def __aenter__(self):
        if self.session is None:
            self.session = AsyncSessionLocal()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            if exc_type:
                await self.session.rollback()
            else:
                await self.session.commit()
            await self.session.close()

    async def execute_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        \"\"\"
        执行原生 SQL 查询，返回字典列表
        :param sql: SQL 查询语句
        :param params: 参数绑定字典
        :return: 查询结果列表
        \"\"\"
        async with self.session.begin() if not self.session.in_transaction() else self:
            result = await self.session.execute(text(sql), params or {})
            columns = result.keys()
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    async def execute_insert(self, table: str, data: Dict[str, Any]) -> int:
        \"\"\"
        插入单条记录
        :param table: 表名
        :param data: 插入数据字典
        :return: 影响行数
        \"\"\"
        columns = ", ".join(data.keys())
        placeholders = ", ".join([f":{key}" for key in data.keys()])
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        async with self.session.begin() if not self.session.in_transaction() else self:
            result = await self.session.execute(text(sql), data)
            return result.rowcount

    async def execute_insert_batch(self, table: str, data_list: List[Dict[str, Any]]) -> int:
        \"\"\"
        批量插入多条记录
        :param table: 表名
        :param data_list: 插入数据字典列表
        :return: 影响行数
        \"\"\"
        if not data_list:
            return 0
        columns = ", ".join(data_list[0].keys())
        placeholders = ", ".join([f":{key}" for key in data_list[0].keys()])
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        total = 0
        async with self.session.begin() if not self.session.in_transaction() else self:
            for data in data_list:
                result = await self.session.execute(text(sql), data)
                total += result.rowcount
            return total

    async def execute_update(self, table: str, data: Dict[str, Any], conditions: Dict[str, Any]) -> int:
        \"\"\"
        更新记录
        :param table: 表名
        :param data: 更新数据字典
        :param conditions: 更新条件字典
        :return: 影响行数
        \"\"\"
        set_clause = ", ".join([f"{key} = :{key}" for key in data.keys()])
        where_clause = " AND ".join([f"{key} = :cond_{key}" for key in conditions.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        params = {**data, **{f"cond_{k}": v for k, v in conditions.items()}}
        async with self.session.begin() if not self.session.in_transaction() else self:
            result = await self.session.execute(text(sql), params)
            return result.rowcount

    async def execute_delete(self, table: str, conditions: Dict[str, Any]) -> int:
        \"\"\"
        删除记录
        :param table: 表名
        :param conditions: 删除条件字典
        :return: 影响行数
        \"\"\"
        where_clause = " AND ".join([f"{key} = :{key}" for key in conditions.keys()])
        sql = f"DELETE FROM {table} WHERE {where_clause}"
        async with self.session.begin() if not self.session.in_transaction() else self:
            result = await self.session.execute(text(sql), conditions)
            return result.rowcount

    async def execute_raw(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Any:
        \"\"\"
        执行任意原生 SQL（适用于 DDL、事务操作等）
        :param sql: SQL 语句
        :param params: 参数绑定字典
        :return: 数据库返回结果
        \"\"\"
        async with self.session.begin() if not self.session.in_transaction() else self:
            result = await self.session.execute(text(sql), params or {})
            return result
""")
```

```
file_write(path="app/db/doris.py", content="""import asyncio
from typing import Any, Dict, List, Optional
import pymysql
from app.core.config import settings

class DorisClient:
    \"\"\"
    Doris 数据库操作工具类
    基于 pymysql 同步连接，通过 asyncio.to_thread 封装为异步接口
    适用于 OLAP 分析查询和大批量数据导入
    \"\"\"

    def __init__(self):
        self.connection: Optional[pymysql.Connection] = None
        self._config = {
            "host": settings.DORIS_HOST,
            "port": settings.DORIS_PORT,
            "user": settings.DORIS_USER,
            "password": settings.DORIS_PASSWORD,
            "database": settings.DORIS_DATABASE,
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor
        }

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self) -> None:
        \"\"\"建立数据库连接\"\"\"
        def _connect():
            return pymysql.connect(**self._config)
        self.connection = await asyncio.to_thread(_connect)

    async def close(self) -> None:
        \"\"\"关闭数据库连接\"\"\"
        if self.connection:
            def _close():
                self.connection.close()
            await asyncio.to_thread(_close)
            self.connection = None

    async def execute_query(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        \"\"\"
        执行查询语句，返回字典列表
        :param sql: SQL 查询语句
        :param params: 参数元组
        :return: 查询结果列表
        \"\"\"
        def _query():
            if not self.connection:
                raise ConnectionError("Doris 数据库未连接，请先调用 connect()")
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params or ())
                return cursor.fetchall()
        return await asyncio.to_thread(_query)

    async def execute_insert(self, table: str, data: Dict[str, Any]) -> int:
        \"\"\"
        插入单条记录
        :param table: 表名
        :param data: 插入数据字典
        :return: 影响行数
        \"\"\"
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        def _insert():
            if not self.connection:
                raise ConnectionError("Doris 数据库未连接，请先调用 connect()")
            with self.connection.cursor() as cursor:
                cursor.execute(sql, tuple(data.values()))
                self.connection.commit()
                return cursor.rowcount
        return await asyncio.to_thread(_insert)

    async def execute_insert_batch(self, table: str, data_list: List[Dict[str, Any]]) -> int:
        \"\"\"
        批量插入多条记录（Doris 推荐大批量导入）
        :param table: 表名
        :param data_list: 插入数据字典列表
        :return: 影响行数
        \"\"\"
        if not data_list:
            return 0
        columns = ", ".join(data_list[0].keys())
        placeholders = ", ".join(["%s"] * len(data_list[0]))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        values = [tuple(d.values()) for d in data_list]
        def _insert_batch():
            if not self.connection:
                raise ConnectionError("Doris 数据库未连接，请先调用 connect()")
            with self.connection.cursor() as cursor:
                cursor.executemany(sql, values)
                self.connection.commit()
                return cursor.rowcount
        return await asyncio.to_thread(_insert_batch)

    async def execute_update(self, table: str, data: Dict[str, Any], conditions: Dict[str, Any]) -> int:
        \"\"\"
        更新记录
        :param table: 表名
        :param data: 更新数据字典
        :param conditions: 更新条件字典
        :return: 影响行数
        \"\"\"
        set_clause = ", ".join([f"{key} = %s" for key in data.keys()])
        where_clause = " AND ".join([f"{key} = %s" for key in conditions.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        params = tuple(data.values()) + tuple(conditions.values())
        def _update():
            if not self.connection:
                raise ConnectionError("Doris 数据库未连接，请先调用 connect()")
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                self.connection.commit()
                return cursor.rowcount
        return await asyncio.to_thread(_update)

    async def execute_delete(self, table: str, conditions: Dict[str, Any]) -> int:
        \"\"\"
        删除记录
        :param table: 表名
        :param conditions: 删除条件字典
        :return: 影响行数
        \"\"\"
        where_clause = " AND ".join([f"{key} = %s" for key in conditions.keys()])
        sql = f"DELETE FROM {table} WHERE {where_clause}"
        params = tuple(conditions.values())
        def _delete():
            if not self.connection:
                raise ConnectionError("Doris 数据库未连接，请先调用 connect()")
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                self.connection.commit()
                return cursor.rowcount
        return await asyncio.to_thread(_delete)

    async def execute_raw(self, sql: str, params: Optional[tuple] = None) -> Any:
        \"\"\"
        执行任意原生 SQL（适用于 DDL、复杂分析查询等）
        :param sql: SQL 语句
        :param params: 参数元组
        :return: 游标对象或影响行数
        \"\"\"
        def _raw():
            if not self.connection:
                raise ConnectionError("Doris 数据库未连接，请先调用 connect()")
            with self.connection.cursor() as cursor:
                affected = cursor.execute(sql, params or ())
                self.connection.commit()
                return affected
        return await asyncio.to_thread(_raw)

    async def stream_load(self, table: str, data: List[Dict[str, Any]], columns: Optional[List[str]] = None) -> Dict[str, Any]:
        \"\"\"
        使用 Doris Stream Load 方式批量导入数据（高性能）
        :param table: 目标表名
        :param data: 数据列表
        :param columns: 指定列顺序（可选）
        :return: Stream Load 返回结果
        \"\"\"
        import json
        import requests
        from app.core.config import settings

        if not data:
            return {"status": "empty", "rows": 0}

        # 构建 CSV 格式数据
        if columns is None:
            columns = list(data[0].keys())

        # 生成 CSV 行
        csv_lines = []
        for row in data:
            csv_line = []
            for col in columns:
                val = row.get(col, "")
                if val is None:
                    csv_line.append("\\\\N")
                elif isinstance(val, (int, float)):
                    csv_line.append(str(val))
                else:
                    # 处理特殊字符
                    str_val = str(val).replace("\\\\", "\\\\\\\\").replace("\\"", "\\\\\\"")
                    csv_line.append(str_val)
            csv_lines.append("\\t".join(csv_line))

        csv_data = "\\n".join(csv_lines)

        # 构建 Stream Load 请求
        url = f"http://{settings.DORIS_HOST}:8030/api/{settings.DORIS_DATABASE}/{table}/_stream_load"
        headers = {
            "Expect": "100-continue",
            "Content-Type": "text/plain; charset=utf-8",
            "columns": ", ".join(columns),
            "format": "csv",
            "column_separator": "\\\\t"
        }

        auth = (settings.DORIS_USER, settings.DORIS_PASSWORD)

        def _stream_load():
            response = requests.put(url, headers=headers, auth=auth, data=csv_data.encode("utf-8"))
            return response.json()

        return await asyncio.to_thread(_stream_load)
""")
```

```
file_write(path="app/models/__init__.py", content="""# SQLAlchemy Models Package
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

# 在此处导入具体模型
# from app.models.user import User
""")
```

```
file_write(path="app/models/user.py", content="""from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.models import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username = Column(String(50), unique=True, nullable=False, comment="用户名")
    email = Column(String(100), unique=True, nullable=False, comment="邮箱")
    full_name = Column(String(100), nullable=True, comment="全名")
    is_active = Column(Boolean, default=True, comment="是否激活")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"
""")
```

```
file_write(path="app/api/__init__.py", content="""# API Routes Package
""")
```

```
file_write(path="app/api/routes/__init__.py", content="""# Route Modules Package
""")
```

```
file_write(path="app/api/routes/health.py", content="""from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db, AsyncSessionLocal
from app.db.doris import DorisClient

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    \"\"\"
    健康检查接口
    返回服务状态及数据库连接状态
    \"\"\"
    status = {
        "service": "running",
        "mysql": "unknown",
        "doris": "unknown"
    }

    # 检查 MySQL 连接
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            status["mysql"] = "connected"
    except Exception as e:
        status["mysql"] = f"error: {str(e)}"

    # 检查 Doris 连接
    try:
        async with DorisClient() as doris:
            await doris.execute_query("SELECT 1")
            status["doris"] = "connected"
    except Exception as e:
        status["doris"] = f"error: {str(e)}"

    return status
""")
```

```
file_write(path="app/api/routes/users.py", content="""from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.core.database import get_db
from app.models.user import User
from app.db.mysql import MySQLClient

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/")
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    \"\"\"获取用户列表\"\"\"
    result = await db.execute(select(User).offset(skip).limit(limit))
    users = result.scalars().all()
    return {"total": len(users), "users": users}

@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    \"\"\"获取单个用户\"\"\"
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.post("/")
async def create_user(
    username: str,
    email: str,
    full_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    \"\"\"创建用户\"\"\"
    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    # 使用 MySQLClient 插入
    async with MySQLClient(session=db) as client:
        data = {
            "username": username,
            "email": email,
            "full_name": full_name or ""
        }
        affected = await client.execute_insert("users", data)
        if affected == 0:
            raise HTTPException(status_code=500, detail="Failed to create user")

    return {"message": "User created successfully", "username": username}
""")
```

```
file_write(path="app/main.py", content="""from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.core.database import init_db, close_db
from app.api.routes.health import router as health_router
from app.api.routes.users import router as users_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    \"\"\"应用生命周期管理\"\"\"
    # 启动时
    await init_db()
    yield
    # 关闭时
    await close_db()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# 注册路由
app.include_router(health_router)
app.include_router(users_router)

@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }
""")
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'fastapi_project'
📄 创建文件 'requirements.txt'
📄 创建文件 '.env'
📄 创建文件 'app/__init__.py'
📄 创建文件 'app/core/__init__.py'
📄 创建文件 'app/core/config.py'
📄 创建文件 'app/core/database.py'
📄 创建文件 'app/db/__init__.py'
📄 创建文件 'app/db/mysql.py'
📄 创建文件 'app/db/doris.py'
📄 创建文件 'app/models/__init__.py'
📄 创建文件 'app/models/user.py'
📄 创建文件 'app/api/__init__.py'
📄 创建文件 'app/api/routes/__init__.py'
📄 创建文件 'app/api/routes/health.py'
📄 创建文件 'app/api/routes/users.py'
📄 创建文件 'app/main.py'