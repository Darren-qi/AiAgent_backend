file_write(path="routes/__init__.py", content="")
file_write(path="routes/auth.py", content="""from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from models import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            flash('请填写用户名和密码', 'danger')
            return render_template('register.html')
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
            return render_template('register.html')
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))
    return render_template('register.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash('用户名或密码错误', 'danger')
            return render_template('login.html')
        login_user(user)
        next_page = request.args.get('next')
        return redirect(next_page or url_for('main.index'))
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))
""")
file_write(path="routes/posts.py", content="""from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from models import Post

posts_bp = Blueprint('posts', __name__)

@posts_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        title = request.form.get('title')
        body = request.form.get('body')
        if not title or not body:
            flash('标题和内容不能为空', 'danger')
            return render_template('create_post.html')
        post = Post(title=title, body=body, author=current_user)
        db.session.add(post)
        db.session.commit()
        flash('文章发布成功', 'success')
        return redirect(url_for('main.index'))
    return render_template('create_post.html')

@posts_bp.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash('您没有权限编辑此文章', 'danger')
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        title = request.form.get('title')
        body = request.form.get('body')
        if not title or not body:
            flash('标题和内容不能为空', 'danger')
            return render_template('edit_post.html', post=post)
        post.title = title
        post.body = body
        db.session.commit()
        flash('文章更新成功', 'success')
        return redirect(url_for('main.post_detail', post_id=post.id))
    return render_template('edit_post.html', post=post)

@posts_bp.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        flash('您没有权限删除此文章', 'danger')
        return redirect(url_for('main.index'))
    db.session.delete(post)
    db.session.commit()
    flash('文章已删除', 'success')
    return redirect(url_for('main.index'))
""")
file_write(path="routes/main.py", content="""from flask import Blueprint, render_template
from models import Post

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    posts = Post.query.order_by(Post.created.desc()).all()
    return render_template('index.html', posts=posts)

@main_bp.route('/post/<int:post_id>')
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('post_detail.html', post=post)
""")
file_write(path="templates/base.html", content="""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Flask博客{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <nav class="navbar">
        <div class="container">
            <a href="{{ url_for('main.index') }}" class="navbar-brand">Flask博客</a>
            <div class="navbar-links">
                {% if current_user.is_authenticated %}
                    <span>欢迎, {{ current_user.username }}</span>
                    <a href="{{ url_for('posts.create') }}">写文章</a>
                    <a href="{{ url_for('auth.logout') }}">退出</a>
                {% else %}
                    <a href="{{ url_for('auth.login') }}">登录</a>
                    <a href="{{ url_for('auth.register') }}">注册</a>
                {% endif %}
            </div>
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
""")
file_write(path="templates/index.html", content="{% extends 'base.html' %}\n{% block title %}首页 - Flask博客{% endblock %}\n{% block content %}\n<h1>最新文章</h1>\n{% if posts %}\n    {% for post in posts %}\n        <div class=\"post-card\">\n            <h2><a href=\"{{ url_for('main.post_detail', post_id=post.id) }}\">{{ post.title }}</a></h2>\n            <p class=\"post-meta\">{{ post.author.username }} · {{ post.created.strftime('%Y-%m-%d %H:%M') }}</p>\n            <p>{{ post.body[:200] }}{% if post.body|length > 200 %}...{% endif %}</p>\n        </div>\n    {% endfor %}\n{% else %}\n    <p>还没有文章，快来写第一篇吧！</p>\n{% endif %}\n{% endblock %}")
file_write(path="templates/post_detail.html", content="{% extends 'base.html' %}\n{% block title %}{{ post.title }} - Flask博客{% endblock %}\n{% block content %}\n<article>\n    <h1>{{ post.title }}</h1>\n    <p class=\"post-meta\">{{ post.author.username }} · {{ post.created.strftime('%Y-%m-%d %H:%M') }}</p>\n    <div class=\"post-body\">{{ post.body }}</div>\n    {% if current_user == post.author %}\n        <div class=\"post-actions\">\n            <a href=\"{{ url_for('posts.edit', post_id=post.id) }}\" class=\"btn\">编辑</a>\n            <form action=\"{{ url_for('posts.delete', post_id=post.id) }}\" method=\"post\" style=\"display:inline;\">\n                <button type=\"submit\" class=\"btn btn-danger\" onclick=\"return confirm('确定删除？')\">删除</button>\n            </form>\n        </div>\n    {% endif %}\n    <a href=\"{{ url_for('main.index') }}\">返回首页</a>\n</article>\n{% endblock %}")
file_write(path="templates/login.html", content="{% extends 'base.html' %}\n{% block title %}登录 - Flask博客{% endblock %}\n{% block content %}\n<h1>登录</h1>\n<form method=\"post\">\n    <div class=\"form-group\">\n        <label for=\"username\">用户名</label>\n        <input type=\"text\" id=\"username\" name=\"username\" required>\n    </div>\n    <div class=\"form-group\">\n        <label for=\"password\">密码</label>\n        <input type=\"password\" id=\"password\" name=\"password\" required>\n    </div>\n    <button type=\"submit\" class=\"btn\">登录</button>\n</form>\n<p>还没有账号？<a href=\"{{ url_for('auth.register') }}\">立即注册</a></p>\n{% endblock %}")
file_write(path="templates/register.html", content="{% extends 'base.html' %}\n{% block title %}注册 - Flask博客{% endblock %}\n{% block content %}\n<h1>注册</h1>\n<form method=\"post\">\n    <div class=\"form-group\">\n        <label for=\"username\">用户名</label>\n        <input type=\"text\" id=\"username\" name=\"username\" required>\n    </div>\n    <div class=\"form-group\">\n        <label for=\"password\">密码</label>\n        <input type=\"password\" id=\"password\" name=\"password\" required>\n    </div>\n    <button type=\"submit\" class=\"btn\">注册</button>\n</form>\n<p>已有账号？<a href=\"{{ url_for('auth.login') }}\">立即登录</a></p>\n{% endblock %}")
file_write(path="templates/create_post.html", content="{% extends 'base.html' %}\n{% block title %}写文章 - Flask博客{% endblock %}\n{% block content %}\n<h1>写文章</h1>\n<form method=\"post\">\n    <div class=\"form-group\">\n        <label for=\"title\">标题</label>\n        <input type=\"text\" id=\"title\" name=\"title\" required>\n    </div>\n    <div class=\"form-group\">\n        <label for=\"body\">内容</label>\n        <textarea id=\"body\" name=\"body\" rows=\"10\" required></textarea>\n    </div>\n    <button type=\"submit\" class=\"btn\">发布</button>\n</form>\n{% endblock %}")
file_write(path="templates/edit_post.html", content="{% extends 'base.html' %}\n{% block title %}编辑文章 - Flask博客{% endblock %}\n{% block content %}\n<h1>编辑文章</h1>\n<form method=\"post\">\n    <div class=\"form-group\">\n        <label for=\"title\">标题</label>\n        <input type=\"text\" id=\"title\" name=\"title\" value=\"{{ post.title }}\" required>\n    </div>\n    <div class=\"form-group\">\n        <label for=\"body\">内容</label>\n        <textarea id=\"body\" name=\"body\" rows=\"10\" required>{{ post.body }}</textarea>\n    </div>\n    <button type=\"submit\" class=\"btn\">保存</button>\n</form>\n{% endblock %}")
file_write(path="static/style.css", content="""* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; background: #f5f5f5; }
.container { max-width: 800px; margin: 0 auto; padding: 0 20px; }
.navbar { background: #2c3e50; color: #fff; padding: 1rem 0; }
.navbar .container { display: flex; justify-content: space-between; align-items: center; }
.navbar-brand { color: #fff; text-decoration: none; font-size: 1.5rem; font-weight: bold; }
.navbar-links a { color: #fff; text-decoration: none; margin-left: 1rem; }
.navbar-links span { margin-left: 1rem; }
h1 { margin: 2rem 0 1rem; }
.post-card { background: #fff; padding: 1.5rem; margin-bottom: 1rem; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
.post-card h2 { margin-bottom: 0.5rem; }
.post-card h2 a { color: #2c3e50; text-decoration: none; }
.post-meta { color: #7f8c8d; font-size: 0.9rem; margin-bottom: 0.5rem; }
.post-body { white-space: pre-wrap; }
.post-actions { margin: 1rem 0; }
.btn { display: inline-block; background: #3498db; color: #fff; padding: 0.5rem 1rem; text-decoration: none; border: none; border-radius: 3px; cursor: pointer; }
.btn-danger { background: #e74c3c; }
.form-group { margin-bottom: 1rem; }
.form-group label { display: block; margin-bottom: 0.3rem; font-weight: bold; }
.form-group input, .form-group textarea { width: 100%; padding: 0.5rem; border: 1px solid #ddd; border-radius: 3px; }
.alert { padding: 0.75rem 1.25rem; margin-bottom: 1rem; border: 1px solid transparent; border-radius: 3px; }
.alert-success { color: #155724; background: #d4edda; border-color: #c3e6cb; }
.alert-danger { color: #721c24; background: #f8d7da; border-color: #f5c6cb; }
""")

STAGE_DONE: development

【工具执行结果】
✅ 创建文件 'routes/__init__.py'
✅ 创建文件 'routes/auth.py'
✅ 创建文件 'routes/posts.py'
✅ 创建文件 'routes/main.py'
✅ 创建文件 'templates/base.html'
✅ 创建文件 'templates/index.html'
✅ 创建文件 'templates/post_detail.html'
✅ 创建文件 'templates/login.html'
✅ 创建文件 'templates/register.html'
✅ 创建文件 'templates/create_post.html'
✅ 创建文件 'templates/edit_post.html'
✅ 创建文件 'static/style.css'