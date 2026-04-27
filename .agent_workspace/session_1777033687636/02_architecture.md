- **技术栈**: Flask, SQLAlchemy, SQLite, Jinja2, Werkzeug(密码哈希), Bootstrap(样式)
- **架构分层**: 
  - `models/` — 数据模型(User, Post)
  - `routes/` — 路由处理(认证、文章CRUD)
  - `templates/` — Jinja2模板
  - `static/` — CSS/JS
- **数据库**: SQLite，两张表: User(id, username, password_hash), Post(id, title, body, created, author_id)
- **关键决策**: 使用Flask-Login管理用户会话，装饰器保护需要登录的路由

STAGE_DONE: architecture