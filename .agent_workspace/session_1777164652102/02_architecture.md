### 技术栈选择
- **后端框架**: Flask 3.x
- **模板引擎**: Jinja2（Flask内置）
- **数据库**: SQLite（开发/轻量部署） + SQLAlchemy ORM
- **前端**: 原生HTML + CSS + Bootstrap 5（快速搭建UI）
- **表单处理**: Flask-WTF（CSRF保护+表单验证）

### 架构分层
```
app/
├── models/      # 数据模型层（SQLAlchemy模型）
├── routes/      # 路由/控制器层（请求处理）
├── templates/   # 视图层（Jinja2模板）
├── forms/       # 表单层（Flask-WTF表单类）
├── static/      # 静态资源（CSS/JS）
└── __init__.py  # 应用工厂
```

### 数据库设计（核心表）
**Post表**:
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| title | String(200) | 文章标题 |
| content | Text | 文章正文 |
| summary | String(500) | 文章摘要 |
| created_at | DateTime | 发布时间 |
| updated_at | DateTime | 最后修改时间 |

### 关键设计决策
- 使用**应用工厂模式**（`create_app()`）提高可测试性和配置灵活性
- 摘要自动截取正文前100字符，减少用户输入负担
- 所有数据库操作在路由函数中完成，保持简单直接
- 使用Bootstrap 5 CDN，无需本地下载依赖

STAGE_DONE: architecture