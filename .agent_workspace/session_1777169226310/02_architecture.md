**技术栈选择：**
- 框架：FastAPI（异步支持、自动API文档）
- 运行：Uvicorn
- 数据验证：Pydantic v2
- 数据库：不强制，预留SQLAlchemy集成位置（示例使用内存数据结构）

**架构分层：**
```
app/
├── main.py          # 应用入口，FastAPI实例化、CORS、路由注册
├── routers/         # 路由处理器（API端点）
│   └── users.py     # 用户相关接口
├── schemas/         # Pydantic模型（请求/响应数据校验）
│   └── user.py
├── models/          # 数据模型定义（ORM模型或数据结构）
│   └── user.py
└── services/        # 业务逻辑层
    └── user_service.py
```

**数据库选型：**
- 当前使用内存字典存储，预留SQLAlchemy集成接口
- 示例使用内存存储，后期可无缝切换

**关键设计决策：**
- 使用 `APIRouter` 模块化路由
- `services/` 层隔离业务逻辑，使路由层保持薄层
- Pydantic schema 与 model 分离，便于版本升级

STAGE_DONE: architecture