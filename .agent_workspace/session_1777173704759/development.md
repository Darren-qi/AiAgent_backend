```
file_write(path="app/api/routes.py", content="""import logging
import time
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any

from app.models.schemas import (
    ParseRequest, ParseResponse, QueryRequest, QueryResponse,
    DatabaseStatus, HealthResponse, ErrorResponse, DatabaseType
)
from app.service.ast_service import ASTService
from app.core.database import db_manager
from app.core.config import settings

logger = logging.getLogger(__name__)

# 创建API路由器
router = APIRouter(prefix="/api", tags=["AST API"])

# 记录服务启动时间
_start_time = time.time()


@router.get("/health", response_model=HealthResponse, summary="健康检查")
async def health_check():
    \"\"\"检查服务运行状态和数据库连接状态\"\"\"
    uptime = time.time() - _start_time
    
    # 获取数据库状态
    mysql_config = None
    doris_config = None
    if settings.mysql:
        mysql_config = {
            "host": settings.mysql.host,
            "port": settings.mysql.port,
            "database": settings.mysql.database,
            "user": settings.mysql.user
        }
    if settings.doris:
        doris_config = {
            "host": settings.doris.host,
            "port": settings.doris.port,
            "database": settings.doris.database,
            "user": settings.doris.user
        }
    
    db_status = DatabaseStatus(
        mysql_connected=db_manager.is_mysql_connected,
        doris_connected=db_manager.is_doris_connected,
        mysql_config=mysql_config,
        doris_config=doris_config
    )
    
    return HealthResponse(
        status="ok",
        version=settings.app.version,
        database=db_status,
        uptime_seconds=round(uptime, 2)
    )


@router.post("/parse", response_model=ParseResponse, summary="解析SQL为AST树")
async def parse_sql(request: ParseRequest):
    \"\"\"将SQL语句解析为AST树结构
    
    - **sql**: 要解析的SQL语句
    - **database_type**: 数据库类型（mysql/doris）
    \"\"\"
    logger.info(f"收到SQL解析请求: {request.sql[:100]}...")
    
    result = ASTService.parse_sql(request.sql)
    
    if not result.success:
        logger.warning(f"SQL解析失败: {result.error}")
    
    return result


@router.post("/validate", summary="验证SQL语法")
async def validate_sql(request: ParseRequest):
    \"\"\"验证SQL语句的语法合法性
    
    - **sql**: 要验证的SQL语句
    - **database_type**: 数据库类型（mysql/doris）
    \"\"\"
    logger.info(f"收到SQL验证请求: {request.sql[:100]}...")
    
    result = ASTService.validate_sql(request.sql)
    
    return result


@router.post("/query", response_model=QueryResponse, summary="执行SQL查询")
async def execute_query(request: QueryRequest):
    \"\"\"执行SQL查询并返回结果
    
    - **sql**: 要执行的SQL语句
    - **database_type**: 目标数据库类型（mysql/doris）
    - **params**: 查询参数（可选）
    - **limit**: 返回行数限制（默认100，最大10000）
    \"\"\"
    logger.info(f"收到查询请求: {request.sql[:100]}..., 目标数据库: {request.database_type}")
    
    result = await ASTService.execute_query(
        sql=request.sql,
        database_type=request.database_type,
        params=request.params
    )
    
    return result


@router.post("/tables", summary="获取数据库表列表")
async def get_tables(database_type: DatabaseType = DatabaseType.MYSQL):
    \"\"\"获取指定数据库中的表列表
    
    - **database_type**: 数据库类型（mysql/doris）
    \"\"\"
    logger.info(f"获取表列表: {database_type}")
    
    from app.dao.mysql_dao import MySQLDAO
    from app.dao.doris_dao import DorisDAO
    
    if database_type == DatabaseType.MYSQL:
        result = await MySQLDAO.get_tables()
    else:
        result = await DorisDAO.get_tables()
    
    return result


@router.post("/schema/{table_name}", summary="获取表结构")
async def get_table_schema(table_name: str, database_type: DatabaseType = DatabaseType.MYSQL):
    \"\"\"获取指定表的字段结构
    
    - **table_name**: 表名
    - **database_type**: 数据库类型（mysql/doris）
    \"\"\"
    logger.info(f"获取表结构: {database_type}.{table_name}")
    
    from app.dao.mysql_dao import MySQLDAO
    from app.dao.doris_dao import DorisDAO
    
    if database_type == DatabaseType.MYSQL:
        result = await MySQLDAO.get_table_schema(table_name)
    else:
        result = await DorisDAO.get_table_schema(table_name)
    
    return result


@router.get("/config", summary="查看当前配置")
async def get_config():
    \"\"\"查看当前应用配置（隐藏密码）\"\"\"
    config_info = {
        "app": {
            "name": settings.app.name,
            "version": settings.app.version,
            "host": settings.app.host,
            "port": settings.app.port,
            "debug": settings.app.debug
        },
        "mysql": None,
        "doris": None,
        "logging": {
            "level": settings.log_level,
            "file": settings.log_file
        }
    }
    
    if settings.mysql:
        config_info["mysql"] = {
            "host": settings.mysql.host,
            "port": settings.mysql.port,
            "database": settings.mysql.database,
            "user": settings.mysql.user,
            "pool_size": settings.mysql.pool_size
        }
    
    if settings.doris:
        config_info["doris"] = {
            "host": settings.doris.host,
            "port": settings.doris.port,
            "database": settings.doris.database,
            "user": settings.doris.user,
            "pool_size": settings.doris.pool_size
        }
    
    return config_info


@router.post("/config/reload", summary="热加载配置")
async def reload_config():
    \"\"\"热加载配置文件\"\"\"
    try:
        settings.reload()
        logger.info("配置热加载成功")
        return {"success": True, "message": "配置热加载成功"}
    except Exception as e:
        logger.error(f"配置热加载失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"配置热加载失败: {str(e)}")


@router.post("/extract/tables", summary="从SQL中提取表名")
async def extract_tables(request: ParseRequest):
    \"\"\"从SQL语句中提取所有引用的表名
    
    - **sql**: 要分析的SQL语句
    - **database_type**: 数据库类型（mysql/doris）
    \"\"\"
    logger.info(f"提取表名: {request.sql[:100]}...")
    
    # 先解析SQL
    parse_result = ASTService.parse_sql(request.sql)
    if not parse_result.success:
        raise HTTPException(status_code=400, detail=parse_result.error)
    
    # 提取表名
    tables = ASTService.extract_table_names(parse_result.ast)
    
    return {
        "success": True,
        "sql": request.sql,
        "tables": tables,
        "table_count": len(tables)
    }


@router.post("/extract/columns", summary="从SQL中提取列名")
async def extract_columns(request: ParseRequest):
    \"\"\"从SQL语句中提取所有引用的列名
    
    - **sql**: 要分析的SQL语句
    - **database_type**: 数据库类型（mysql/doris）
    \"\"\"
    logger.info(f"提取列名: {request.sql[:100]}...")
    
    # 先解析SQL
    parse_result = ASTService.parse_sql(request.sql)
    if not parse_result.success:
        raise HTTPException(status_code=400, detail=parse_result.error)
    
    # 提取列名
    columns = ASTService.extract_columns(parse_result.ast)
    
    return {
        "success": True,
        "sql": request.sql,
        "columns": columns,
        "column_count": len(columns)
    }


@router.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    \"\"\"全局异常处理\"\"\"
    logger.error(f"全局异常: {str(exc)}", exc_info=True)
    return ErrorResponse(
        error_code="INTERNAL_ERROR",
        message="服务器内部错误",
        detail=str(exc),
        timestamp=datetime.now().isoformat()
    )
""")
```

```
file_write(path="main.py", content="""#!/usr/bin/env python3
\"\"\"
AST API Framework - 主入口文件
基于FastAPI的AST解析和查询框架，支持MySQL和Doris双数据源
\"\"\"

import os
import sys
import logging
from pathlib import Path

# 确保项目根目录在Python路径中
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import db_manager
from app.api.routes import router

# 配置日志
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format=settings.log_format,
    handlers=[
        logging.FileHandler(settings.log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    \"\"\"应用生命周期管理\"\"\"
    logger.info("=" * 50)
    logger.info(f"AST API Framework v{settings.app.version} 启动中...")
    logger.info(f"应用名称: {settings.app.name}")
    logger.info(f"调试模式: {settings.app.debug}")
    logger.info("=" * 50)
    
    # 启动时初始化数据库连接
    try:
        await db_manager.initialize()
        logger.info("数据库连接初始化完成")
    except Exception as e:
        logger.error(f"数据库连接初始化失败: {str(e)}")
        logger.warning("服务将以无数据库模式运行")
    
    yield
    
    # 关闭时清理资源
    logger.info("正在关闭服务...")
    try:
        await db_manager.close_all()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接时出错: {str(e)}")
    logger.info("服务已停止")


# 创建FastAPI应用实例
app = FastAPI(
    title=settings.app.name,
    description=\"\"\"
    AST API Framework - 基于抽象语法树的SQL解析与查询框架
    
    ## 功能特点
    - **SQL解析**: 将SQL语句解析为AST树结构
    - **多数据库支持**: 同时支持MySQL和Doris
    - **语法验证**: 验证SQL语句的合法性
    - **表结构查询**: 获取数据库表和字段信息
    - **配置热加载**: 支持运行时动态更新配置
    
    ## 使用场景
    - SQL分析和优化工具
    - 多数据源查询网关
    - 数据库元数据管理
    \"\"\",
    version=settings.app.version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)


@app.get("/", tags=["Root"])
async def root():
    \"\"\"根路径 - 返回API基本信息\"\"\"
    return {
        "name": settings.app.name,
        "version": settings.app.version,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/api/health",
        "status": "running"
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    \"\"\"返回空favicon\"\"\"
    return {}


def main():
    \"\"\"主函数 - 启动服务\"\"\"
    logger.info(f"启动服务: {settings.app.host}:{settings.app.port}")
    uvicorn.run(
        "main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=settings.app.debug,
        log_level=settings.log_level.lower() if settings.log_level else "info"
    )


if __name__ == "__main__":
    main()
""")
```

```
file_write(path=".env", content="""# AST API Framework 环境变量配置
# 优先级高于config.yaml

# 应用配置
AST_APP__NAME=AST API Framework
AST_APP__VERSION=1.0.0
AST_APP__HOST=0.0.0.0
AST_APP__PORT=8000
AST_APP__DEBUG=true

# MySQL数据库配置
AST_MYSQL__HOST=localhost
AST_MYSQL__PORT=3306
AST_MYSQL__USER=root
AST_MYSQL__PASSWORD=root123
AST_MYSQL__DATABASE=ast_framework

# Doris数据库配置
AST_DORIS__HOST=localhost
AST_DORIS__PORT=9030
AST_DORIS__USER=root
AST_DORIS__PASSWORD=
AST_DORIS__DATABASE=ast_olap

# 日志配置
AST_LOG_LEVEL=INFO
AST_LOG_FILE=logs/ast_api.log
""")
```

```
file_write(path="Dockerfile", content="""FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc \\
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建日志目录
RUN mkdir -p logs

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""")
```

```
file_write(path="docker-compose.yml", content="""version: '3.8'

services:
  ast-api:
    build: .
    container_name: ast-api-framework
    ports:
      - "8000:8000"
    environment:
      - AST_APP__HOST=0.0.0.0
      - AST_APP__PORT=8000
      - AST_APP__DEBUG=false
      - AST_MYSQL__HOST=mysql
      - AST_MYSQL__PORT=3306
      - AST_MYSQL__USER=root
      - AST_MYSQL__PASSWORD=root123
      - AST_MYSQL__DATABASE=ast_framework
      - AST_DORIS__HOST=doris
      - AST_DORIS__PORT=9030
      - AST_DORIS__USER=root
      - AST_DORIS__PASSWORD=
      - AST_DORIS__DATABASE=ast_olap
    volumes:
      - ./logs:/app/logs
      - ./config:/app/config
    depends_on:
      - mysql
      - doris
    restart: unless-stopped
    networks:
      - ast-network

  mysql:
    image: mysql:8.0
    container_name: ast-mysql
    environment:
      MYSQL_ROOT_PASSWORD: root123
      MYSQL_DATABASE: ast_framework
    ports:
      - "3307:3306"
    volumes:
      - mysql-data:/var/lib/mysql
    restart: unless-stopped
    networks:
      - ast-network

  doris:
    image: apache/doris:latest
    container_name: ast-doris
    environment:
      - FE_SERVERS=fe1:localhost:9010
    ports:
      - "9031:9030"
    restart: unless-stopped
    networks:
      - ast-network

volumes:
  mysql-data:

networks:
  ast-network:
    driver: bridge
""")
```

```
file_write(path="README.md", content="""# AST API Framework

基于FastAPI的AST（抽象语法树）解析和查询框架，支持MySQL和Doris双数据源。

## 功能特点

- **SQL解析**: 将SQL语句解析为AST树结构，支持SELECT/INSERT/UPDATE/DELETE等
- **多数据库支持**: 同时支持MySQL和Doris，通过配置切换
- **语法验证**: 验证SQL语句的合法性
- **表结构查询**: 获取数据库表和字段信息
- **配置热加载**: 支持运行时动态更新配置
- **自动文档**: 内置Swagger和ReDoc API文档
- **分层架构**: Controller/Service/DAO清晰分层

## 快速开始

### 环境要求

- Python 3.10+
- MySQL 8.0+（可选）
- Doris（可选）

### 安装

```bash
# 克隆项目
git clone <your-repo-url>
cd ast-api-framework

# 安装依赖
pip install -r requirements.txt

# 修改配置
cp config/config.yaml config/config.yaml.bak
# 编辑 config/config.yaml 配置数据库连接

# 启动服务
python main.py
```

### 使用Docker

```bash
# 构建和启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f ast-api
```

## API文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 主要接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/parse` | POST | 解析SQL为AST树 |
| `/api/validate` | POST | 验证SQL语法 |
| `/api/query` | POST | 执行SQL查询 |
| `/api/tables` | POST | 获取表列表 |
| `/api/schema/{table}` | POST | 获取表结构 |
| `/api/config` | GET | 查看配置 |
| `/api/config/reload` | POST | 热加载配置 |
| `/api/extract/tables` | POST | 提取表名 |
| `/api/extract/columns` | POST | 提取列名 |

## 项目结构

```
ast-api-framework/
├── app/
│   ├── api/          # Controller层：路由和请求处理
│   ├── service/      # Service层：业务逻辑和AST解析
│   ├── dao/          # DAO层：数据库连接和查询
│   ├── core/         # 核心工具：配置、数据库引擎
│   └── models/       # 数据模型和DTO
├── config/           # 配置文件
├── logs/             # 日志文件
├── main.py           # 应用入口
├── requirements.txt  # Python依赖
├── Dockerfile        # Docker构建文件
└── docker-compose.yml # Docker编排文件
```

## 配置说明

配置文件 `config/config.yaml` 支持以下配置：

```yaml
app:
  name: AST API Framework
  version: 1.0.0
  host: 0.0.0.0
  port: 8000

databases:
  mysql:
    enabled: true
    host: localhost
    port: 3306
    user: root
    password: root123
    database: ast_framework
    pool_size: 10

  doris:
    enabled: true
    host: localhost
    port: 9030
    user: root
    password: ""
    database: ast_olap
    pool_size: 5
```

## 开发指南

### 添加新接口

1. 在 `app/models/schemas.py` 中定义请求/响应模型
2. 在 `app/service/` 中实现业务逻辑
3. 在 `app/dao/` 中实现数据访问
4. 在 `app/api/routes.py` 中添加路由

### 添加新数据库

1. 在 `app/core/config.py` 中添加数据库配置模型
2. 在 `app/core/database.py` 中添加连接管理
3. 在 `app/dao/` 中创建新的DAO类

## 许可证

MIT License
""")
```

**文件清单（共20个文件已创建）：**

| 文件路径 | 说明 |
|---------|------|
| `requirements.txt` | Python依赖配置 |
| `.env` | 环境变量配置 |
| `config/config.yaml` | 应用配置文件 |
| `main.py` | 应用主入口 |
| `Dockerfile` | Docker构建文件 |
| `docker-compose.yml` | Docker编排文件 |
| `README.md` | 项目文档 |
| `app/__init__.py` | 应用包初始化 |
| `app/core/__init__.py` | 核心工具包 |
| `app/core/config.py` | 配置管理（支持YAML+环境变量） |
| `app/core/database.py` | 数据库连接管理器（MySQL+Doris双数据源） |
| `app/models/__init__.py` | 数据模型包 |
| `app/models/schemas.py` | 请求/响应模型定义 |
| `app/dao/__init__.py` | DAO层包 |
| `app/dao/mysql_dao.py` | MySQL数据访问对象 |
| `app/dao/doris_dao.py` | Doris数据访问对象 |
| `app/service/__init__.py` | Service层包 |
| `app/service/ast_service.py` | AST解析服务（核心业务逻辑） |
| `app/api/__init__.py` | API路由包 |
| `app/api/routes.py` | API路由定义（10个接口） |

**框架已实现的功能：**
1. ✅ **分层架构**：Controller（routes.py）→ Service（ast_service.py）→ DAO（mysql_dao.py, doris_dao.py）
2. ✅ **MySQL连接管理**：通过SQLAlchemy异步引擎，支持连接池
3. ✅ **Doris连接管理**：通过SQLAlchemy异步引擎，支持OLAP查询
4. ✅ **AST解析引擎**：使用sqlparse将SQL解析为AST树结构
5. ✅ **配置管理**：支持YAML配置文件和环境变量，支持热加载
6. ✅ **10个API接口**：健康检查、SQL解析、SQL验证、查询执行、表列表、表结构、配置查看、配置热加载、提取表名、提取列名
7. ✅ **自动API文档**：Swagger UI（/docs）和ReDoc（/redoc）
8. ✅ **Docker支持**：Dockerfile + docker-compose.yml
9. ✅ **统一异常处理**：全局异常捕获
10. ✅ **CORS支持**：跨域资源共享

STAGE_DONE: development

【工具执行结果】
📄 创建文件 'app/api/routes.py'
📄 创建文件 'main.py'
📄 创建文件 '.env'
📄 创建文件 'Dockerfile'
📄 创建文件 'docker-compose.yml'
📄 创建文件 'README.md'