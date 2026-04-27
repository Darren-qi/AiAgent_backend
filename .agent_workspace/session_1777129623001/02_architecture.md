### 技术栈选择
- **后端框架**：Flask
- **数据库**：SQLite（开发/轻量部署），使用Flask-SQLAlchemy ORM
- **模板引擎**：Jinja2（Flask内置）
- **用户认证**：Flask-Login + Werkzeug密码哈希
- **表单处理**：Flask-WTF（CSRF保护）
- **前端**：Bootstrap 5（快速样式）+ 原生JavaScript

### 架构分层
```
┌─────────────────────┐
│  路由层 (routes)     │ ← 请求入口，视图函数
├─────────────────────┤
│  业务逻辑层 (services)│ ← 文章/用户业务逻辑
├─────────────────────┤
│  数据访问层 (models)  │ ← SQLAlchemy模型
├─────────────────────┤
│  DB (SQLite)         │
└─────────────────────┘
```

### 数据库设计（核心表）
- **User**: id, username, email, password_hash, created_at
- **Post**: id, title, body, created_at, updated_at, author_id (FK → User)

### 关键设计决策
- 使用Flask蓝图（Blueprint）组织路由，便于后续扩展
- 文章内容支持Markdown（可选扩展）
- 密码存储使用Werkzeug的generate_password_hash/check_password_hash
- 创建/编辑/删除文章接口需登录保护（@login_required）

STAGE_DONE: architecture