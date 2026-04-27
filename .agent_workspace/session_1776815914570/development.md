project_create("flask_todo_api")

file_write(path="requirements.txt", content="Flask==2.3.3
Flask-SQLAlchemy==3.0.5
Flask-Migrate==4.0.4
python-dotenv==1.0.0")

file_write(path="app.py", content="from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    
    # 配置数据库
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///todo.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
    
    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    
    # 注册蓝图
    from routes.todo_routes import todo_bp
    app.register_blueprint(todo_bp)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)")

file_write(path=".env", content="DATABASE_URL=sqlite:///todo.db
SECRET_KEY=your-secret-key-here
FLASK_APP=app.py
FLASK_ENV=development")

file_write(path=".gitignore", content="# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
env.bak/
venv.bak/

# Flask
instance/
.webassets-cache

# SQLite
*.sqlite
*.sqlite3

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Environment variables
.env
.env.local
.env.*.local

# Logs
*.log")

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'flask_todo_api'
📄 创建文件 'requirements.txt'
📄 创建文件 'app.py'
📄 创建文件 '.env'
📄 创建文件 '.gitignore'