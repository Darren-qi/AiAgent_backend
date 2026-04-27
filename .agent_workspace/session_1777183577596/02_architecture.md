### 技术栈选择
- **框架**: FastAPI + Uvicorn
- **数据库**: MySQL (SQLAlchemy ORM) + Doris (pymysql 原生SQL)
- **配置管理**: pydantic-settings
- **数据校验**: pydantic

### 架构分层
```
project/
├── app/
│   ├── api/            # 接口层 - 路由定义
│   ├── core/           # 核心配置 - 数据库连接、配置
│   ├── models/         # 数据模型 - SQLAlchemy ORM模型
│   ├── schemas/        # Pydantic校验模型
│   ├── services/       # 业务逻辑层
│   └── utils/          # 工具类 - MySQL/Doris封装
├── config.py           # 配置管理
├── main.py             # 入口
└── requirements.txt
```

### 数据库设计决策
- **MySQL**: 使用SQLAlchemy ORM，适合结构化数据、事务性操作
- **Doris**: 使用pymysql原生SQL，适合OLAP分析查询，不建立ORM映射

### 关键设计决策
1. MySQL工具类提供ORM级别的CRUD操作
2. Doris工具类提供原生SQL执行接口，支持批量导入和复杂查询
3. 配置统一管理，通过.env文件切换数据库连接

STAGE_DONE: architecture