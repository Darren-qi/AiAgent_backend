**功能清单**
1.  项目初始化：创建标准的FastAPI项目目录结构。
2.  核心应用：包含主应用文件（`main.py`），定义FastAPI应用实例和根路由。
3.  路由模块化：创建独立的路由文件（如 `api/` 目录），演示如何组织端点。
4.  依赖管理：包含 `requirements.txt` 文件，列出核心依赖（FastAPI, uvicorn）。
5.  运行配置：提供启动应用的命令和说明。

**验收标准**
1.  执行 `python main.py` 或 `uvicorn main:app --reload` 后，应用能成功启动。
2.  访问 `http://127.0.0.1:8000` 能返回默认的欢迎信息或API文档链接。
3.  访问 `http://127.0.0.1:8000/docs` 能打开自动生成的交互式API文档。

STAGE_DONE: requirements