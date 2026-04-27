### 需求文档

**功能清单：**
1. FastAPI应用启动入口 — 包含基本的FastAPI应用实例化、CORS配置
2. 健康检查接口 — 提供 `/health` 端点，返回服务运行状态
3. 示例API路由 — 提供一个简单的CRUD示例路由（如用户管理），包含GET/POST方法
4. 项目结构分层 — 按 `app/` 主目录组织代码，包含 `routers/`、`models/`、`schemas/`、`services/` 子模块

**验收标准（用户视角）：**
- 用户可以通过 `uvicorn app.main:app --reload` 启动服务，无报错
- 用户访问 `http://localhost:8000/health` 能收到 `{"status": "ok"}` 响应
- 用户访问 `http://localhost:8000/docs` 能看到Swagger文档界面
- 用户可以调用示例接口（如用户列表GET /users）并得到正确响应

STAGE_DONE: requirements