### 技术栈选择
- **Web框架**: FastAPI + Uvicorn
- **数据库ORM**: SQLAlchemy 2.0（异步支持）
- **数据库驱动**: aiomysql（MySQL）、pymysql（Doris，因为Doris兼容MySQL协议但异步支持有限）
- **配置管理**: pydantic-settings（基于环境变量/.env文件）
- **依赖管理**: pip + requirements.txt

### 架构分层
```
app/
├── core/           # 核心配置
│   ├── config.py   # 配置管理（数据库连接参数等）
│   └── database.py # 数据库引擎、会话工厂
├── db/             # 数据库工具类
│   ├── mysql.py    # MySQL操作类
│   └── doris.py    # Doris操作类
├── models/         # SQLAlchemy模型定义（可选）
├── api/            # 路由层
│   └── routes/
│       └── health.py  # 健康检查接口
├── main.py         # FastAPI应用入口
└── requirements.txt
```

### 数据库选型
- **MySQL**: 关系型数据库，使用SQLAlchemy异步引擎（aiomysql驱动）
- **Doris**: 兼容MySQL协议的分析型数据库，使用同步引擎（pymysql驱动），但封装为异步接口（run_in_executor）

### 关键设计决策
1. **MySQL操作类**: 基于SQLAlchemy的`async session`，提供`execute_query`、`execute_insert`、`execute_update`、`execute_delete`等通用方法
2. **Doris操作类**: 基于pymysql同步连接，使用`asyncio.to_thread`包裹为异步调用，提供类似接口
3. **配置管理**: 使用`.env`文件存放数据库连接信息，通过pydantic-settings自动加载
4. **健康检查**: 提供`GET /health`端点，返回服务状态及数据库连接状态

STAGE_DONE: architecture