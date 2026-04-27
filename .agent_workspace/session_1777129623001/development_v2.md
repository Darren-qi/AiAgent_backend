file_write(path="routes/__init__.py", content="")
file_write(path="routes/auth.py", content="""from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from models import User
from forms import LoginForm, RegisterForm

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录！', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', form=form)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            flash('登录成功！', 'success')
            return redirect(next_page) if next_page else redirect(url_for('main.index'))
        flash('用户名或密码错误', 'danger')
    return render_template('auth/login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('main.index'))
""")
file_write(path="routes/posts.py", content="""from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from models import Post
from forms import PostForm

posts_bp = Blueprint('posts', __name__)

@posts_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = PostForm()
    if form.validate_on_submit():
        post = Post(title=form.title.data, body=form.body.data, author=current_user)
        db.session.add(post)
        db.session.commit()
        flash('文章发布成功！', 'success')
        return redirect(url_for('main.post', post_id=post.id))
    return render_template('posts/create.html', form=form)

@posts_bp.route('/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)
    form = PostForm()
    if form.validate_on_submit():
        post.title = form.title.data
        post.body = form.body.data
        db.session.commit()
        flash('文章更新成功！', 'success')
        return redirect(url_for('main.post', post_id=post.id))
    form.title.data = post.title
    form.body.data = post.body
    return render_template('posts/edit.html', form=form, post=post)

@posts_bp.route('/<int:post_id>/delete', methods=['POST'])
@login_required
def delete(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash('文章已删除', 'info')
    return redirect(url_for('main.index'))
""")
file_write(path="routes/main.py", content="""from flask import Blueprint, render_template, abort
from models import Post

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('index.html', posts=posts)

@main_bp.route('/post/<int:post_id>')
def post(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('post.html', post=post)
""")
file_write(path="forms.py", content="""from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from models import User

class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    remember = BooleanField('记住我')
    submit = SubmitField('登录')

class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField('邮箱', validators=[DataRequired(), Email()])
    password = PasswordField('密码', validators=[DataRequired(), Length(min=6)])
    password2 = PasswordField('确认密码', validators=[DataRequired(), EqualTo('password', message='两次密码不一致')])
    submit = SubmitField('注册')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('用户名已存在')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('邮箱已被注册')

class PostForm(FlaskForm):
    title = StringField('标题', validators=[DataRequired(), Length(max=200)])
    body = TextAreaField('内容', validators=[DataRequired()])
    submit = SubmitField('发布')
""")
file_write(path="templates/base.html", content="""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Flask博客{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('main.index') }}">Flask博客</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav ms-auto">
                    {% if current_user.is_authenticated %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('posts.create') }}">写文章</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#">{{ current_user.username }}</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('auth.logout') }}">退出</a>
                        </li>
                    {% else %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('auth.login') }}">登录</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('auth.register') }}">注册</a>
                        </li>
                    {% endif %}
                </ul>
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

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
""")
file_write(path="templates/index.html", content="""{% extends "base.html" %}
{% block title %}首页 - Flask博客{% endblock %}
{% block content %}
    <h1 class="mb-4">最新文章</h1>
    {% if posts %}
        <div class="row">
            {% for post in posts %}
                <div class="col-md-6 mb-4">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title">
                                <a href="{{ url_for('main.post', post_id=post.id) }}" class="text-decoration-none">
                                    {{ post.title }}
                                </a>
                            </h5>
                            <p class="card-text text-muted">
                                <small>
                                    作者：{{ post.author.username }} | 
                                    发布于：{{ post.created_at.strftime('%Y-%m-%d %H:%M') }}
                                </small>
                            </p>
                            <p class="card-text">{{ post.body[:200] }}{% if post.body|length > 200 %}...{% endif %}</p>
                            <a href="{{ url_for('main.post', post_id=post.id) }}" class="btn btn-primary btn-sm">阅读全文</a>
                        </div>
                    </div>
                </div>
            {% endfor %}
        </div>
    {% else %}
        <div class="alert alert-info">
            暂无文章，{% if current_user.is_authenticated %}
                <a href="{{ url_for('posts.create') }}">写第一篇</a>
            {% else %}
                <a href="{{ url_for('auth.login') }}">登录</a>后发布文章
            {% endif %}
        </div>
    {% endif %}
{% endblock %}
""")
file_write(path="templates/post.html", content="""{% extends "base.html" %}
{% block title %}{{ post.title }} - Flask博客{% endblock %}
{% block content %}
    <article>
        <h1>{{ post.title }}</h1>
        <p class="text-muted">
            <small>
                作者：{{ post.author.username }} | 
                发布于：{{ post.created_at.strftime('%Y-%m-%d %H:%M') }}
                {% if post.updated_at != post.created_at %}
                    | 更新于：{{ post.updated_at.strftime('%Y-%m-%d %H:%M') }}
                {% endif %}
            </small>
        </p>
        <hr>
        <div class="post-body">
            {{ post.body | safe }}
        </div>
        {% if current_user == post.author %}
            <div class="mt-4">
                <a href="{{ url_for('posts.edit', post_id=post.id) }}" class="btn btn-warning">编辑</a>
                <form action="{{ url_for('posts.delete', post_id=post.id) }}" method="POST" style="display:inline;">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <button type="submit" class="btn btn-danger" onclick="return confirm('确定删除？')">删除</button>
                </form>
            </div>
        {% endif %}
    </article>
{% endblock %}
""")
file_write(path="templates/auth/login.html", content="""{% extends "base.html" %}
{% block title %}登录 - Flask博客{% endblock %}
{% block content %}
    <div class="row justify-content-center">
        <div class="col-md-6">
            <h2 class="mb-4">登录</h2>
            <form method="POST">
                {{ form.hidden_tag() }}
                <div class="mb-3">
                    {{ form.username.label(class="form-label") }}
                    {{ form.username(class="form-control" + (" is-invalid" if form.username.errors else "")) }}
                    {% for error in form.username.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <div class="mb-3">
                    {{ form.password.label(class="form-label") }}
                    {{ form.password(class="form-control" + (" is-invalid" if form.password.errors else "")) }}
                    {% for error in form.password.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <div class="mb-3 form-check">
                    {{ form.remember(class="form-check-input") }}
                    {{ form.remember.label(class="form-check-label") }}
                </div>
                <button type="submit" class="btn btn-primary">登录</button>
                <a href="{{ url_for('auth.register') }}" class="btn btn-link">没有账号？注册</a>
            </form>
        </div>
    </div>
{% endblock %}
""")
file_write(path="templates/auth/register.html", content="""{% extends "base.html" %}
{% block title %}注册 - Flask博客{% endblock %}
{% block content %}
    <div class="row justify-content-center">
        <div class="col-md-6">
            <h2 class="mb-4">注册</h2>
            <form method="POST">
                {{ form.hidden_tag() }}
                <div class="mb-3">
                    {{ form.username.label(class="form-label") }}
                    {{ form.username(class="form-control" + (" is-invalid" if form.username.errors else "")) }}
                    {% for error in form.username.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <div class="mb-3">
                    {{ form.email.label(class="form-label") }}
                    {{ form.email(class="form-control" + (" is-invalid" if form.email.errors else "")) }}
                    {% for error in form.email.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <div class="mb-3">
                    {{ form.password.label(class="form-label") }}
                    {{ form.password(class="form-control" + (" is-invalid" if form.password.errors else "")) }}
                    {% for error in form.password.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <div class="mb-3">
                    {{ form.password2.label(class="form-label") }}
                    {{ form.password2(class="form-control" + (" is-invalid" if form.password2.errors else "")) }}
                    {% for error in form.password2.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <button type="submit" class="btn btn-primary">注册</button>
                <a href="{{ url_for('auth.login') }}" class="btn btn-link">已有账号？登录</a>
            </form>
        </div>
    </div>
{% endblock %}
""")
file_write(path="templates/posts/create.html", content="""{% extends "base.html" %}
{% block title %}写文章 - Flask博客{% endblock %}
{% block content %}
    <div class="row justify-content-center">
        <div class="col-md-8">
            <h2 class="mb-4">写文章</h2>
            <form method="POST">
                {{ form.hidden_tag() }}
                <div class="mb-3">
                    {{ form.title.label(class="form-label") }}
                    {{ form.title(class="form-control" + (" is-invalid" if form.title.errors else ""), rows="1") }}
                    {% for error in form.title.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <div class="mb-3">
                    {{ form.body.label(class="form-label") }}
                    {{ form.body(class="form-control" + (" is-invalid" if form.body.errors else ""), rows="10") }}
                    {% for error in form.body.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <button type="submit" class="btn btn-primary">发布</button>
                <a href="{{ url_for('main.index') }}" class="btn btn-secondary">取消</a>
            </form>
        </div>
    </div>
{% endblock %}
""")
file_write(path="templates/posts/edit.html", content="""{% extends "base.html" %}
{% block title %}编辑文章 - Flask博客{% endblock %}
{% block content %}
    <div class="row justify-content-center">
        <div class="col-md-8">
            <h2 class="mb-4">编辑文章</h2>
            <form method="POST">
                {{ form.hidden_tag() }}
                <div class="mb-3">
                    {{ form.title.label(class="form-label") }}
                    {{ form.title(class="form-control" + (" is-invalid" if form.title.errors else ""), rows="1") }}
                    {% for error in form.title.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <div class="mb-3">
                    {{ form.body.label(class="form-label") }}
                    {{ form.body(class="form-control" + (" is-invalid" if form.body.errors else ""), rows="10") }}
                    {% for error in form.body.errors %}
                        <div class="invalid-feedback">{{ error }}</div>
                    {% endfor %}
                </div>
                <button type="submit" class="btn btn-primary">更新</button>
                <a href="{{ url_for('main.post', post_id=post.id) }}" class="btn btn-secondary">取消</a>
            </form>
        </div>
    </div>
{% endblock %}
""")
file_write(path="static/style.css", content="""body {
    background-color: #f8f9fa;
}

.card {
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    transition: transform 0.2s;
}

.card:hover {
    transform: translateY(-2px);
}

.post-body {
    line-height: 1.8;
    font-size: 1.1rem;
}

.navbar {
    margin-bottom: 2rem;
}
""")

STAGE_DONE: development

【工具执行结果】
📄 创建文件 'routes/__init__.py'
📄 创建文件 'routes/auth.py'
📄 创建文件 'routes/posts.py'
📄 创建文件 'routes/main.py'
📄 创建文件 'forms.py'
📄 创建文件 'templates/base.html'
📄 创建文件 'templates/index.html'
📄 创建文件 'templates/post.html'
📄 创建文件 'templates/auth/login.html'
📄 创建文件 'templates/auth/register.html'
📄 创建文件 'templates/posts/create.html'
📄 创建文件 'templates/posts/edit.html'
📄 创建文件 'static/style.css'