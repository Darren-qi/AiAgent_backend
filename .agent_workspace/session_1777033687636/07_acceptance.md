**PASS: 最终验收通过**

### 验收标准逐项检查：

1. ✅ **用户在浏览器打开首页，能看到博客文章列表**
   - `main.py` 的 `index()` 路由查询所有文章并按时间倒序排列
   - `index.html` 模板渲染文章卡片（标题、作者、时间、摘要）

2. ✅ **用户点击文章标题，能跳转到文章详情页并看到完整内容**
   - `main.py` 的 `post_detail()` 路由根据ID查询文章
   - `post_detail.html` 显示完整标题、作者、时间和正文内容

3. ✅ **用户可以注册新账号并登录系统**
   - `auth.py` 的 `register()` 路由：表单提交、用户名唯一性校验、密码哈希存储
   - `auth.py` 的 `login()` 路由：用户验证、Flask-Login会话管理

4. ✅ **登录后用户可以创建新文章（标题+正文）**
   - `posts.py` 的 `create()` 路由：`@login_required` 保护，表单验证标题和正文
   - `create_post.html` 提供标题输入框和正文文本域

5. ✅ **登录后用户可以编辑或删除自己创建的文章**
   - `posts.py` 的 `edit()` 路由：验证作者身份，更新标题和正文
   - `posts.py` 的 `delete()` 路由：验证作者身份，删除文章
   - 详情页 `post_detail.html` 中仅显示当前用户的编辑/删除按钮

6. ✅ **未登录用户只能浏览文章，不能进行管理操作**
   - 所有管理路由（create/edit/delete）均使用 `@login_required` 装饰器
   - 未登录访问管理路由会自动跳转到登录页面

### 项目结构完整性：
- 入口文件：`app.py`（工厂函数、Blueprint注册、数据库初始化）
- 配置：`config.py`（密钥、数据库URI）
- 模型：`models.py`（User + Post + 密码哈希 + Flask-Login回调）
- 路由：`routes/auth.py`（注册/登录/登出）、`routes/posts.py`（CRUD）、`routes/main.py`（首页/详情）
- 模板：`templates/` 下6个模板（base、index、post_detail、login、register、create、edit）
- 样式：`static/style.css`（完整样式：导航、卡片、表单、按钮、消息提示）
- 依赖：`requirements.txt`（Flask、Flask-SQLAlchemy、Flask-Login、Werkzeug）

write_artifact(stage="acceptance", content="最终验收通过：Flask博客项目完整实现了所有功能，代码可运行，满足用户需求。")

STAGE_DONE: acceptance