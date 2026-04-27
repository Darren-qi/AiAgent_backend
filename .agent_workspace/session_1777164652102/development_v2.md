### 第二批：业务逻辑文件

```
file_write(path="app/models.py", content="from app import db\nfrom datetime import datetime\n\nclass Post(db.Model):\n    __tablename__ = 'posts'\n    \n    id = db.Column(db.Integer, primary_key=True)\n    title = db.Column(db.String(200), nullable=False)\n    content = db.Column(db.Text, nullable=False)\n    summary = db.Column(db.String(500))\n    created_at = db.Column(db.DateTime, default=datetime.utcnow)\n    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)\n\n    def __repr__(self):\n        return f'<Post {self.title}>'")
```

```
file_write(path="app/forms.py", content="from flask_wtf import FlaskForm\nfrom wtforms import StringField, TextAreaField, SubmitField\nfrom wtforms.validators import DataRequired, Length\n\nclass PostForm(FlaskForm):\n    title = StringField('标题', validators=[DataRequired(), Length(max=200)])\n    content = TextAreaField('正文', validators=[DataRequired()])\n    submit = SubmitField('提交')")
```

```
file_write(path="app/routes.py", content="from flask import Blueprint, render_template, redirect, url_for, flash, request\nfrom app import db\nfrom app.models import Post\nfrom app.forms import PostForm\n\nblog_bp = Blueprint('blog', __name__)\n\n@blog_bp.route('/')\ndef index():\n    posts = Post.query.order_by(Post.created_at.desc()).all()\n    return render_template('index.html', posts=posts)\n\n@blog_bp.route('/post/<int:post_id>')\ndef post_detail(post_id):\n    post = Post.query.get_or_404(post_id)\n    return render_template('detail.html', post=post)\n\n@blog_bp.route('/create', methods=['GET', 'POST'])\ndef create_post():\n    form = PostForm()\n    if form.validate_on_submit():\n        summary = form.content.data[:100].replace('\\n', ' ') if len(form.content.data) > 100 else form.content.data.replace('\\n', ' ')\n        post = Post(title=form.title.data, content=form.content.data, summary=summary)\n        db.session.add(post)\n        db.session.commit()\n        flash('文章发布成功！', 'success')\n        return redirect(url_for('blog.post_detail', post_id=post.id))\n    return render_template('create.html', form=form)\n\n@blog_bp.route('/edit/<int:post_id>', methods=['GET', 'POST'])\ndef edit_post(post_id):\n    post = Post.query.get_or_404(post_id)\n    form = PostForm(obj=post)\n    if form.validate_on_submit():\n        post.title = form.title.data\n        post.content = form.content.data\n        post.summary = form.content.data[:100].replace('\\n', ' ') if len(form.content.data) > 100 else form.content.data.replace('\\n', ' ')\n        db.session.commit()\n        flash('文章更新成功！', 'success')\n        return redirect(url_for('blog.post_detail', post_id=post.id))\n    return render_template('edit.html', form=form, post=post)\n\n@blog_bp.route('/delete/<int:post_id>', methods=['POST'])\ndef delete_post(post_id):\n    post = Post.query.get_or_404(post_id)\n    db.session.delete(post)\n    db.session.commit()\n    flash('文章已删除！', 'success')\n    return redirect(url_for('blog.index'))")
```

STAGE_DONE: development

【工具执行结果】
📄 创建文件 'app/models.py'
📄 创建文件 'app/forms.py'
📄 创建文件 'app/routes.py'

[UI Designer]: ## 对话
好的，路由和业务逻辑已经完成。现在我来设计并创建前端模板页面。

## 思考
需要创建4个模板文件：基础模板、文章列表页、文章详情页、文章创建/编辑页。

## 决策
采用Bootstrap 5构建响应式UI，统一使用基础模板。

## 行动
### 创建模板文件

```
file_write(path="app/templates/base.html", content="""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Flask 博客{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('blog.index') }}">Flask 博客</a>
            <div class="navbar-nav">
                <a class="nav-link" href="{{ url_for('blog.index') }}">首页</a>
                <a class="nav-link" href="{{ url_for('blog.create_post') }}">发布文章</a>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>""")
```

```
file_write(path="app/templates/index.html", content="""{% extends 'base.html' %}

{% block title %}首页 - Flask 博客{% endblock %}

{% block content %}
    <h1 class="mb-4">文章列表</h1>
    
    {% if posts %}
        <div class="row">
            {% for post in posts %}
                <div class="col-md-6 mb-4">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title">
                                <a href="{{ url_for('blog.post_detail', post_id=post.id) }}" class="text-decoration-none">
                                    {{ post.title }}
                                </a>
                            </h5>
                            <p class="card-text text-muted">{{ post.summary }}</p>
                            <p class="card-text">
                                <small class="text-muted">
                                    发布于 {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}
                                </small>
                            </p>
                            <a href="{{ url_for('blog.post_detail', post_id=post.id) }}" class="btn btn-primary btn-sm">阅读更多</a>
                        </div>
                    </div>
                </div>
            {% endfor %}
        </div>
    {% else %}
        <div class="alert alert-info">
            还没有文章，<a href="{{ url_for('blog.create_post') }}" class="alert-link">点击发布第一篇</a>
        </div>
    {% endif %}
{% endblock %}""")
```

```
file_write(path="app/templates/detail.html", content="""{% extends 'base.html' %}

{% block title %}{{ post.title }} - Flask 博客{% endblock %}

{% block content %}
    <nav aria-label="breadcrumb">
        <ol class="breadcrumb">
            <li class="breadcrumb-item"><a href="{{ url_for('blog.index') }}">首页</a></li>
            <li class="breadcrumb-item active">{{ post.title }}</li>
        </ol>
    </nav>

    <article>
        <h1>{{ post.title }}</h1>
        <p class="text-muted">
            发布于 {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}
            {% if post.updated_at != post.created_at %}
                | 最后编辑于 {{ post.updated_at.strftime('%Y-%m-%d %H:%M') }}
            {% endif %}
        </p>
        <hr>
        <div class="mt-4">
            {{ post.content | replace('\\n', '<br>') | safe }}
        </div>
    </article>

    <div class="mt-4">
        <a href="{{ url_for('blog.edit_post', post_id=post.id) }}" class="btn btn-warning">编辑</a>
        <form action="{{ url_for('blog.delete_post', post_id=post.id) }}" method="POST" style="display: inline;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <button type="submit" class="btn btn-danger" onclick="return confirm('确定要删除这篇文章吗？')">删除</button>
        </form>
        <a href="{{ url_for('blog.index') }}" class="btn btn-secondary">返回首页</a>
    </div>
{% endblock %}""")
```

```
file_write(path="app/templates/create.html", content="""{% extends 'base.html' %}

{% block title %}发布文章 - Flask 博客{% endblock %}

{% block content %}
    <h1 class="mb-4">发布新文章</h1>
    
    <form method="POST" action="{{ url_for('blog.create_post') }}">
        {{ form.hidden_tag() }}
        
        <div class="mb-3">
            {{ form.title.label(class='form-label') }}
            {{ form.title(class='form-control' + (' is-invalid' if form.title.errors else '')) }}
            {% for error in form.title.errors %}
                <div class="invalid-feedback">{{ error }}</div>
            {% endfor %}
        </div>
        
        <div class="mb-3">
            {{ form.content.label(class='form-label') }}
            {{ form.content(class='form-control' + (' is-invalid' if form.content.errors else ''), rows=10) }}
            {% for error in form.content.errors %}
                <div class="invalid-feedback">{{ error }}</div>
            {% endfor %}
        </div>
        
        {{ form.submit(class='btn btn-primary') }}
        <a href="{{ url_for('blog.index') }}" class="btn btn-secondary">取消</a>
    </form>
{% endblock %}""")
```

```
file_write(path="app/templates/edit.html", content="""{% extends 'base.html' %}

{% block title %}编辑文章 - Flask 博客{% endblock %}

{% block content %}
    <h1 class="mb-4">编辑文章</h1>
    
    <form method="POST" action="{{ url_for('blog.edit_post', post_id=post.id) }}">
        {{ form.hidden_tag() }}
        
        <div class="mb-3">
            {{ form.title.label(class='form-label') }}
            {{ form.title(class='form-control' + (' is-invalid' if form.title.errors else '')) }}
            {% for error in form.title.errors %}
                <div class="invalid-feedback">{{ error }}</div>
            {% endfor %}
        </div>
        
        <div class="mb-3">
            {{ form.content.label(class='form-label') }}
            {{ form.content(class='form-control' + (' is-invalid' if form.content.errors else ''), rows=10) }}
            {% for error in form.content.errors %}
                <div class="invalid-feedback">{{ error }}</div>
            {% endfor %}
        </div>
        
        {{ form.submit(class='btn btn-primary') }}
        <a href="{{ url_for('blog.post_detail', post_id=post.id) }}" class="btn btn-secondary">取消</a>
    </form>
{% endblock %}""")
```

STAGE_DONE: ui_design

【工具执行结果】
📄 创建文件 'app/templates/base.html'
📄 创建文件 'app/templates/index.html'
📄 创建文件 'app/templates/detail.html'
📄 创建文件 'app/templates/create.html'
📄 创建文件 'app/templates/edit.html'

[QAEngineer]: ## 对话
好的，我来检查这个Flask博客项目是否完整且可运行。

## 思考
需要读取所有关键文件来验证代码完整性，确认是否满足所有功能需求。

## 决策
先查看项目目录结构，再读取关键文件内容。

## 行动
```
file_list(path="flask_blog_1777164668")
```

```
file_read(path="flask_blog_1777164668/requirements.txt")
```

```
file_read(path="flask_blog_1777164668/.env")
```

```
file_read(path="flask_blog_1777164668/run.py")
```

```
file_read(path="flask_blog_1777164668/app/__init__.py")
```

```
file_read(path="flask_blog_1777164668/app/models.py")
```

```
file_read(path="flask_blog_1777164668/app/forms.py")
```

```
file_read(path="flask_blog_1777164668/app/routes.py")
```

```
file_read(path="flask_blog_1777164668/app/templates/base.html")
```

```
file_read(path="flask_blog_1777164668/app/templates/index.html")
```

```
file_read(path="flask_blog_1777164668/app/templates/detail.html")
```

```
file_read(path="flask_blog_1777164668/app/templates/create.html")
```

```
file_read(path="flask_blog_1777164668/app/templates/edit.html")
```