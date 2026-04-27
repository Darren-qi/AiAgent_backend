### 自检阶段：读取并完善文件

```
file_read(path="app/core/config.py")
```

```
file_read(path="app/core/database.py")
```

```
file_read(path="app/db/mysql.py")
```

```
file_read(path="app/db/doris.py")
```

```
file_read(path="app/models/user.py")
```

```
file_read(path="app/api/routes/health.py")
```

```
file_read(path="app/api/routes/users.py")
```

```
file_read(path="app/main.py")
```

### 完善代码：补充错误处理和输入验证

```
file_write(path="app/db/mysql.py", content="""from typing import Any, Dict, List, Optional, Union
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal

class MySQLClient:
    \"\"\"
    MySQL 数据库操作工具类
    基于 SQLAlchemy 异步会话，提供通用的 CRUD 操作方法
    支持上下文管理器自动管理事务和会话生命周期
    \"\"\"

    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session
        self._own_session = session is None

    async def __aenter__(self):
        if self.session is None:
            self.session = AsyncSessionLocal()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and self._own_session:
            try:
                if exc_type:
                    await self.session.rollback()
                else:
                    await self.session.commit()
            finally:
                await self.session.close()
                self.session = None

    async def _ensure_session(self):
        \"\"\"确保会话已创建\"\"\"
        if self.session is None:
            self.session = AsyncSessionLocal()
            self._own_session = True

    async def execute_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        \"\"\"
        执行原生 SQL 查询，返回字典列表
        :param sql: SQL 查询语句（支持 :param 命名参数绑定）
        :param params: 参数绑定字典，如 {"id": 1}
        :return: 查询结果列表，每行一个字典
        :raises ValueError: SQL 语句为空时抛出
        :raises Exception: 数据库执行错误
        \"\"\"
        if not sql or not sql.strip():
            raise ValueError("SQL 查询语句不能为空")

        await self._ensure_session()
        try:
            result = await self.session.execute(text(sql), params or {})
            columns = result.keys()
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            raise Exception(f"MySQL 查询执行失败: {str(e)}") from e

    async def execute_insert(self, table: str, data: Dict[str, Any]) -> int:
        \"\"\"
        插入单条记录
        :param table: 表名（注意 SQL 注入风险，建议使用白名单校验）
        :param data: 插入数据字典，如 {"name": "test", "age": 18}
        :return: 影响行数
        :raises ValueError: 表名或数据为空时抛出
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not data:
            raise ValueError("插入数据不能为空")

        columns = ", ".join(data.keys())
        placeholders = ", ".join([f":{key}" for key in data.keys()])
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

        await self._ensure_session()
        try:
            result = await self.session.execute(text(sql), data)
            return result.rowcount
        except Exception as e:
            raise Exception(f"MySQL 插入失败 (表: {table}): {str(e)}") from e

    async def execute_insert_batch(self, table: str, data_list: List[Dict[str, Any]]) -> int:
        \"\"\"
        批量插入多条记录
        :param table: 表名
        :param data_list: 插入数据字典列表，所有字典必须包含相同的键
        :return: 影响行数
        :raises ValueError: 数据列表为空或键不一致时抛出
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not data_list:
            return 0

        # 校验所有字典键一致
        keys = set(data_list[0].keys())
        for i, data in enumerate(data_list):
            if set(data.keys()) != keys:
                raise ValueError(f"第 {i+1} 条数据字段不一致: 期望 {keys}, 实际 {set(data.keys())}")

        columns = ", ".join(data_list[0].keys())
        placeholders = ", ".join([f":{key}" for key in data_list[0].keys()])
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

        await self._ensure_session()
        total = 0
        try:
            for data in data_list:
                result = await self.session.execute(text(sql), data)
                total += result.rowcount
            return total
        except Exception as e:
            raise Exception(f"MySQL 批量插入失败 (表: {table}): {str(e)}") from e

    async def execute_update(self, table: str, data: Dict[str, Any], conditions: Dict[str, Any]) -> int:
        \"\"\"
        更新记录
        :param table: 表名
        :param data: 更新数据字典，如 {"name": "new_name"}
        :param conditions: 更新条件字典，如 {"id": 1}
        :return: 影响行数
        :raises ValueError: 条件为空时抛出
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not data:
            raise ValueError("更新数据不能为空")
        if not conditions:
            raise ValueError("更新条件不能为空，禁止无条件更新")

        set_clause = ", ".join([f"{key} = :{key}" for key in data.keys()])
        where_clause = " AND ".join([f"{key} = :cond_{key}" for key in conditions.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        params = {**data, **{f"cond_{k}": v for k, v in conditions.items()}}

        await self._ensure_session()
        try:
            result = await self.session.execute(text(sql), params)
            return result.rowcount
        except Exception as e:
            raise Exception(f"MySQL 更新失败 (表: {table}): {str(e)}") from e

    async def execute_delete(self, table: str, conditions: Dict[str, Any]) -> int:
        \"\"\"
        删除记录
        :param table: 表名
        :param conditions: 删除条件字典，如 {"id": 1}
        :return: 影响行数
        :raises ValueError: 条件为空时抛出（禁止全表删除）
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not conditions:
            raise ValueError("删除条件不能为空，禁止无条件删除")

        where_clause = " AND ".join([f"{key} = :{key}" for key in conditions.keys()])
        sql = f"DELETE FROM {table} WHERE {where_clause}"

        await self._ensure_session()
        try:
            result = await self.session.execute(text(sql), conditions)
            return result.rowcount
        except Exception as e:
            raise Exception(f"MySQL 删除失败 (表: {table}): {str(e)}") from e

    async def execute_raw(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Any:
        \"\"\"
        执行任意原生 SQL（适用于 DDL、事务操作等）
        :param sql: SQL 语句
        :param params: 参数绑定字典
        :return: 数据库返回结果（CursorResult 对象）
        \"\"\"
        if not sql or not sql.strip():
            raise ValueError("SQL 语句不能为空")

        await self._ensure_session()
        try:
            result = await self.session.execute(text(sql), params or {})
            return result
        except Exception as e:
            raise Exception(f"MySQL 原生 SQL 执行失败: {str(e)}") from e
""")
```

```
file_write(path="app/db/doris.py", content="""import asyncio
from typing import Any, Dict, List, Optional, Tuple
import pymysql
from pymysql.cursors import DictCursor
from app.core.config import settings

class DorisClient:
    \"\"\"
    Doris 数据库操作工具类
    基于 pymysql 同步连接，通过 asyncio.to_thread 封装为异步接口
    支持上下文管理器自动管理连接生命周期
    适用于 OLAP 分析查询、大批量数据导入（Stream Load）
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
            "cursorclass": DictCursor,
            "autocommit": False
        }

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self) -> None:
        \"\"\"建立 Doris 数据库连接\"\"\"
        if self.connection:
            return
        def _connect():
            try:
                return pymysql.connect(**self._config)
            except pymysql.Error as e:
                raise ConnectionError(f"Doris 连接失败: {e}") from e
        self.connection = await asyncio.to_thread(_connect)

    async def close(self) -> None:
        \"\"\"关闭 Doris 数据库连接\"\"\"
        if self.connection:
            def _close():
                try:
                    self.connection.close()
                except pymysql.Error:
                    pass
            await asyncio.to_thread(_close)
            self.connection = None

    async def _ensure_connected(self):
        \"\"\"确保连接已建立\"\"\"
        if not self.connection:
            await self.connect()
        else:
            # 检查连接是否有效
            try:
                def _ping():
                    self.connection.ping(reconnect=True)
                await asyncio.to_thread(_ping)
            except (pymysql.Error, AttributeError):
                await self.connect()

    async def execute_query(self, sql: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        \"\"\"
        执行查询语句，返回字典列表
        :param sql: SQL 查询语句
        :param params: 参数元组，如 (1, "test")
        :return: 查询结果列表，每行一个字典
        :raises ValueError: SQL 为空时抛出
        \"\"\"
        if not sql or not sql.strip():
            raise ValueError("SQL 查询语句不能为空")

        await self._ensure_connected()
        def _query():
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params or ())
                return cursor.fetchall()
        try:
            return await asyncio.to_thread(_query)
        except pymysql.Error as e:
            raise Exception(f"Doris 查询执行失败: {e}") from e

    async def execute_insert(self, table: str, data: Dict[str, Any]) -> int:
        \"\"\"
        插入单条记录
        :param table: 表名
        :param data: 插入数据字典
        :return: 影响行数
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not data:
            raise ValueError("插入数据不能为空")

        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

        await self._ensure_connected()
        def _insert():
            with self.connection.cursor() as cursor:
                cursor.execute(sql, tuple(data.values()))
                self.connection.commit()
                return cursor.rowcount
        try:
            return await asyncio.to_thread(_insert)
        except pymysql.Error as e:
            raise Exception(f"Doris 插入失败 (表: {table}): {e}") from e

    async def execute_insert_batch(self, table: str, data_list: List[Dict[str, Any]]) -> int:
        \"\"\"
        批量插入多条记录
        :param table: 表名
        :param data_list: 插入数据字典列表
        :return: 影响行数
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not data_list:
            return 0

        columns = ", ".join(data_list[0].keys())
        placeholders = ", ".join(["%s"] * len(data_list[0]))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        values = [tuple(d.values()) for d in data_list]

        await self._ensure_connected()
        def _insert_batch():
            with self.connection.cursor() as cursor:
                cursor.executemany(sql, values)
                self.connection.commit()
                return cursor.rowcount
        try:
            return await asyncio.to_thread(_insert_batch)
        except pymysql.Error as e:
            raise Exception(f"Doris 批量插入失败 (表: {table}): {e}") from e

    async def execute_update(self, table: str, data: Dict[str, Any], conditions: Dict[str, Any]) -> int:
        \"\"\"
        更新记录
        :param table: 表名
        :param data: 更新数据字典
        :param conditions: 更新条件字典
        :return: 影响行数
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not data:
            raise ValueError("更新数据不能为空")
        if not conditions:
            raise ValueError("更新条件不能为空，禁止无条件更新")

        set_clause = ", ".join([f"{key} = %s" for key in data.keys()])
        where_clause = " AND ".join([f"{key} = %s" for key in conditions.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        params = tuple(data.values()) + tuple(conditions.values())

        await self._ensure_connected()
        def _update():
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                self.connection.commit()
                return cursor.rowcount
        try:
            return await asyncio.to_thread(_update)
        except pymysql.Error as e:
            raise Exception(f"Doris 更新失败 (表: {table}): {e}") from e

    async def execute_delete(self, table: str, conditions: Dict[str, Any]) -> int:
        \"\"\"
        删除记录
        :param table: 表名
        :param conditions: 删除条件字典
        :return: 影响行数
        \"\"\"
        if not table or not table.strip():
            raise ValueError("表名不能为空")
        if not conditions:
            raise ValueError("删除条件不能为空，禁止无条件删除")

        where_clause = " AND ".join([f"{key} = %s" for key in conditions.keys()])
        sql = f"DELETE FROM {table} WHERE {where_clause}"
        params = tuple(conditions.values())

        await self._ensure_connected()
        def _delete():
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                self.connection.commit()
                return cursor.rowcount
        try:
            return await asyncio.to_thread(_delete)
        except pymysql.Error as e:
            raise Exception(f"Doris 删除失败 (表: {table}): {e}") from e

    async def execute_raw(self, sql: str, params: Optional[Tuple] = None) -> int:
        \"\"\"
        执行任意原生 SQL（适用于 DDL、复杂分析查询等）
        :param sql: SQL 语句
        :param params: 参数元组
        :return: 影响行数
        \"\"\"
        if not sql or not sql.strip():
            raise ValueError("SQL 语句不能为空")

        await self._ensure_connected()
        def _raw():
            with self.connection.cursor() as cursor:
                affected = cursor.execute(sql, params or ())
                self.connection.commit()
                return affected
        try:
            return await asyncio.to_thread(_raw)
        except pymysql.Error as e:
            raise Exception(f"Doris 原生 SQL 执行失败: {e}") from e

    async def stream_load(self, table: str, data: List[Dict[str, Any]], columns: Optional[List[str]] = None, label: Optional[str] = None) -> Dict[str, Any]:
        \"\"\"
        使用 Doris Stream Load 方式批量导入数据（高性能，推荐大批量使用）
        :param table: 目标表名
        :param data: 数据列表
        :param columns: 指定列顺序（可选，默认使用第一条数据的键）
        :param label: 导入标签（可选，用于去重）
        :return: Stream Load 返回结果字典
        \"\"\"
        import json
        import requests

        if not data:
            return {"Status": "Success", "NumberLoadedRows": 0, "NumberTotalRows": 0}

        if columns is None:
            columns = list(data[0].keys())

        # 生成 CSV 格式数据（Tab 分隔）
        csv_lines = []
        for row in data:
            csv_line = []
            for col in columns:
                val = row.get(col)
                if val is None:
                    csv_line.append("\\\\N")
                elif isinstance(val, (int, float)):
                    csv_line.append(str(val))
                else:
                    str_val = str(val).replace("\\\\", "\\\\\\\\").replace("\\t", " ")
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
        if label:
            headers["label"] = label

        auth = (settings.DORIS_USER, settings.DORIS_PASSWORD)

        def _stream_load():
            try:
                response = requests.put(
                    url,
                    headers=headers,
                    auth=auth,
                    data=csv_data.encode("utf-8"),
                    timeout=300
                )
                result = response.json()
                if result.get("Status") != "Success":
                    raise Exception(f"Stream Load 失败: {result}")
                return result
            except requests.RequestException as e:
                raise Exception(f"Stream Load 请求失败: {e}") from e

        return await asyncio.to_thread(_stream_load)
""")
```

```
file_write(path="app/api/routes/users.py", content="""from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field
from app.core.database import get_db
from app.models.user import User
from app.db.mysql import MySQLClient

router = APIRouter(prefix="/users", tags=["users"])

# Pydantic 请求/响应模型
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: str = Field(..., description="邮箱地址")
    full_name: Optional[str] = Field(None, max_length=100, description="全名")

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True

class UserListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    users: List[UserResponse]

@router.get("/", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db)
):
    \"\"\"获取用户列表（分页）\"\"\"
    # 查询总数
    count_result = await db.execute(select(func.count(User.id)))
    total = count_result.scalar() or 0

    # 查询分页数据
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User).offset(offset).limit(page_size).order_by(User.id)
    )
    users = result.scalars().all()

    return UserListResponse(
        total=total,
        page=page,
        page_size=page_size,
        users=[UserResponse.model_validate(u) for u in users]
    )

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    \"\"\"根据 ID 获取单个用户\"\"\"
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserResponse.model_validate(user)

@router.post("/", response_model=dict, status_code=201)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    \"\"\"创建新用户\"\"\"
    # 参数校验
    if not user_data.username.strip():
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if "@" not in user_data.email:
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="用户名已存在")

    # 检查邮箱是否已存在
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="邮箱已被注册")

    # 使用 MySQLClient 插入用户
    async with MySQLClient(session=db) as client:
        insert_data = {
            "username": user_data.username.strip(),
            "email": user_data.email.strip().lower(),
            "full_name": user_data.full_name.strip() if user_data.full_name else ""
        }
        affected = await client.execute_insert("users", insert_data)
        if affected == 0:
            raise HTTPException(status_code=500, detail="创建用户失败")

    return {
        "message": "用户创建成功",
        "username": user_data.username,
        "email": user_data.email
    }

@router.put("/{user_id}", response_model=dict)
async def update_user(
    user_id: int,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    \"\"\"更新用户信息\"\"\"
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    # 检查用户是否存在
    result = await db.execute(select(User).where(User.id == user_id))
    existing_user = result.scalar_one_or_none()
    if not existing_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 检查用户名是否被其他用户使用
    result = await db.execute(
        select(User).where(User.username == user_data.username, User.id != user_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="用户名已被其他用户使用")

    # 使用 MySQLClient 更新
    async with MySQLClient(session=db) as client:
        update_data = {
            "username": user_data.username.strip(),
            "email": user_data.email.strip().lower(),
            "full_name": user_data.full_name.strip() if user_data.full_name else ""
        }
        conditions = {"id": user_id}
        affected = await client.execute_update("users", update_data, conditions)
        if affected == 0:
            raise HTTPException(status_code=500, detail="更新用户失败")

    return {
        "message": "用户更新成功",
        "user_id": user_id
    }

@router.delete("/{user_id}", response_model=dict)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):
    \"\"\"删除用户\"\"\"
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    # 检查用户是否存在
    result = await db.execute(select(User).where(User.id == user_id))
    existing_user = result.scalar_one_or_none()
    if not existing_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 使用 MySQLClient 删除
    async with MySQLClient(session=db) as client:
        conditions = {"id": user_id}
        affected = await client.execute_delete("users", conditions)
        if affected == 0:
            raise HTTPException(status_code=500, detail="删除用户失败")

    return {
        "message": "用户删除成功",
        "user_id": user_id
    }
""")
```

```
file_write(path="app/api/routes/health.py", content="""from fastapi import APIRouter
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.db.doris import DorisClient

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    \"\"\"
    健康检查接口
    返回服务状态以及 MySQL、Doris 数据库的连接状态
    \"\"\"
    status = {
        "service": "running",
        "version": "1.0.0",
        "mysql": "unknown",
        "doris": "unknown"
    }

    # 检查 MySQL 连接
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1 AS alive"))
            row = result.fetchone()
            if row and row[0] == 1:
                status["mysql"] = "connected"
            else:
                status["mysql"] = "unexpected_response"
    except Exception as e:
        status["mysql"] = f"error: {str(e)}"

    # 检查 Doris 连接
    try:
        async with DorisClient() as doris:
            result = await doris.execute_query("SELECT 1 AS alive")
            if result and result[0].get("alive") == 1:
                status["doris"] = "connected"
            else:
                status["doris"] = "unexpected_response"
    except Exception as e:
        status["doris"] = f"error: {str(e)}"

    return status
""")
```

```
file_write(path="app/models/user.py", content="""from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.models import Base

class User(Base):
    \"\"\"用户模型\"\"\"
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    email = Column(String(100), unique=True, nullable=False, index=True, comment="邮箱")
    full_name = Column(String(100), nullable=True, comment="全名")
    is_active = Column(Boolean, default=True, comment="是否激活")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"

    def to_dict(self):
        \"\"\"转换为字典\"\"\"
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
""")
```

```
file_write(path="app/core/database.py", content="""from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from app.core.config import settings

# 构建 MySQL 异步连接 URL
MYSQL_URL = (
    f"mysql+aiomysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
    f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}"
    f"?charset=utf8mb4"
)

# 创建异步引擎
async_engine = create_async_engine(
    MYSQL_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600  # 1小时后回收连接
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db() -> AsyncSession:
    \"\"\"
    获取数据库会话的依赖注入
    用于 FastAPI 路由中自动管理会话生命周期
    使用方式: db: AsyncSession = Depends(get_db)
    \"\"\"
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
    \"\"\"初始化数据库连接池\"\"\"
    try:
        # 测试数据库连接
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        print(f"[Database] MySQL 连接成功: {settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}")
    except Exception as e:
        print(f"[Database] MySQL 连接失败: {e}")
        print("[Database] 服务将继续启动，但数据库相关功能不可用")

async def close_db():
    \"\"\"关闭数据库连接池\"\"\"
    try:
        await async_engine.dispose()
        print("[Database] MySQL 连接池已关闭")
    except Exception as e:
        print(f"[Database] 关闭连接池时出错: {e}")
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
        case_sensitive = True

settings = Settings()

# 验证配置
def validate_settings():
    \"\"\"验证关键配置项\"\"\"
    errors = []
    if not settings.MYSQL_HOST:
        errors.append("MYSQL_HOST 不能为空")
    if not settings.MYSQL_DATABASE:
        errors.append("MYSQL_DATABASE 不能为空")
    if not settings.DORIS_HOST:
        errors.append("DORIS_HOST 不能为空")
    if not settings.DORIS_DATABASE:
        errors.append("DORIS_DATABASE 不能为空")
    if errors:
        raise ValueError("配置验证失败: " + "; ".join(errors))

# 启动时验证配置
validate_settings()
""")
```

```
file_write(path="app/main.py", content="""from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db, close_db
from app.api.routes.health import router as health_router
from app.api.routes.users import router as users_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    \"\"\"应用生命周期管理\"\"\"
    # 启动时执行
    print(f"[App] {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    await init_db()
    print(f"[App] {settings.APP_NAME} 启动完成")
    yield
    # 关闭时执行
    print("[App] 服务关闭中...")
    await close_db()
    print("[App] 服务已关闭")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于 FastAPI 的项目框架，集成 MySQL 和 Doris 数据库操作工具类",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 注册 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")

@app.get("/")
async def root():
    \"\"\"根路径，返回服务基本信息\"\"\"
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": "/api/v1/health"
    }

@app.get("/api/v1")
async def api_root():
    \"\"\"API 根路径\"\"\"
    return {
        "message": f"Welcome to {settings.APP_NAME} API",
        "version": settings.APP_VERSION,
        "endpoints": {
            "health": "/api/v1/health",
            "users": "/api/v1/users"
        }
    }
""")
```

```
file_write(path="requirements.txt", content="""fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy[asyncio]==2.0.23
aiomysql==0.2.0
pymysql==1.1.0
pydantic-settings==2.1.0
python-dotenv==1.0.0
requests==2.31.0
pydantic[email]==2.5.2
""")
```

STAGE_DONE: development

【工具执行结果】
📄 创建文件 'app/db/mysql.py'
📄 创建文件 'app/db/doris.py'
📄 创建文件 'app/api/routes/users.py'
📄 创建文件 'app/api/routes/health.py'
📄 创建文件 'app/models/user.py'
📄 创建文件 'app/core/database.py'
📄 创建文件 'app/core/config.py'
📄 创建文件 'app/main.py'
📄 创建文件 'requirements.txt'