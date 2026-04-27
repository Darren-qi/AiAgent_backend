### 架构设计总结

## 技术栈
- **框架**: FastAPI 0.104+
- **ORM**: SQLAlchemy 2.0
- **验证**: Pydantic v2
- **认证**: JWT (python-jose) + bcrypt
- **数据库**: SQLite (开发) / PostgreSQL (生产)
- **缓存**: Redis (可选)
- **迁移**: Alembic
- **测试**: pytest + httpx

## 架构分层

```
┌─────────────────────────────────────────────────┐
│                  API 层 (Routers)                │
│   health.py  |  auth.py  |  users.py            │
├─────────────────────────────────────────────────┤
│              服务层 (Services)                   │
│   user_service.py  |  auth_service.py           │
├─────────────────────────────────────────────────┤
│             仓储层 (Repositories)                │
│   base.py  |  user_repository.py                │
├─────────────────────────────────────────────────┤
│              模型层 (Models)                     │
│   base.py  |  user.py                           │
├─────────────────────────────────────────────────┤
│              数据层 (Database)                   │
│   session.py  |  base.py                        │
└─────────────────────────────────────────────────┘
```

## 关键设计决策

1. **分层架构**: 采用经典的4层架构（API → 服务 → 仓储 → 数据），每层职责单一，便于测试和扩展
2. **依赖注入**: 使用FastAPI的Depends系统实现依赖注入，Service和Repository通过DI解耦
3. **统一响应**: 所有API返回统一的 `ResponseModel` 格式，包含 `code/message/data`
4. **异常处理**: 自定义 `AppException` 体系，配合全局异常处理器统一错误响应格式
5. **配置管理**: 使用 `pydantic-settings` 从环境变量/`.env` 文件读取配置，支持多环境
6. **安全认证**: JWT令牌认证，密码使用bcrypt哈希存储，OAuth2标准流程
7. **中间件**: 请求日志、CORS、性能监控等中间件可插拔设计

## 使用方式

```bash
# 安装依赖
pip install -r requirements.txt

# 复制环境配置
cp .env.example .env

# 启动服务
uvicorn app.main:app --reload

# 访问文档
http://localhost:8000/docs
```

STAGE_DONE: architecture