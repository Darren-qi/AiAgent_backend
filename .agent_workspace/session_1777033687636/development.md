project_create("flask_blog")
file_write(path="app.py", content="""from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    from routes.auth import auth_bp
    from routes.posts import posts_bp
    from routes.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()

    return app
""")
file_write(path="config.py", content="""import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///blog.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
""")
file_write(path="models.py", content="""from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    posts = db.relationship('Post', backref='author', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f'<Post {self.title}>'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
""")
file_write(path="requirements.txt", content="""Flask==2.3.3
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.2
Werkzeug==2.3.7
""")

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'flask_blog'
📄 创建文件 'app.py'
📄 创建文件 'config.py'
📄 创建文件 'models.py'
📄 创建文件 'requirements.txt'