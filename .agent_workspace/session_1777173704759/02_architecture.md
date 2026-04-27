### 技术栈选择
- **Web框架**：FastAPI（高性能、自动文档）
- **ORM/数据库连接**：SQLAlchemy + PyMySQL（MySQL）/ pydoris（Doris）
- **AST解析**：sqlparse（Python SQL解析库）
- **配置管理**：pydantic-settings（环境变量+YAML）
- **异步支持**：FastAPI原生异步 + async SQLAlchemy

### 架构分层
```
ast-api-framework/
├── app/
│   ├── api/          # Controller层：路由和请求处理
│   ├── service/      # Service层：业务逻辑和AST解析
│   ├── dao/          # DAO层：数据库连接和查询
│   ├── core/         # 核心工具：配置、数据库引擎管理
│   └── models/       # 数据模型和DTO
├── config/           # 配置文件
└── main.py           # 应用入口
```

### 数据库选型
- **MySQL**：SQLAlchemy + PyMySQL（关系型数据存储）
- **Doris**：SQLAlchemy + pydoris（OLAP分析查询）

### 关键设计决策
1. **数据库连接池**：使用SQLAlchemy的异步引擎，支持MySQL和Doris双数据源
2. **AST解析**：使用sqlparse将SQL解析为AST树结构，支持自定义遍历
3. **配置热加载**：通过pydantic-settings支持配置文件动态刷新
4. **统一异常处理**：全局异常捕获，统一错误响应格式

### 创建项目结构
```
ast-api-framework/
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── service/
│   │   ├── __init__.py
│   │   └── ast_service.py
│   ├── dao/
│   │   ├── __init__.py
│   │   ├── mysql_dao.py
│   │   └── doris_dao.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── database.py
│   └── models/
│       ├── __init__.py
│       └── schemas.py
├── config/
│   └── config.yaml
├── requirements.txt
└── main.py
```

STAGE_DONE: architecture