**需求分析更新：**
- **功能清单：**
    1. 程序能够运行。
    2. 程序运行时，在控制台输出“Hello World”文本。
    3. 程序运行时，在控制台输出一条欢迎信息。
    4. 程序结构简单明了。

- **验收标准（用户视角）：**
    1. 用户可以运行程序。
    2. 用户运行程序后，能在控制台看到“Hello World”。
    3. 用户运行程序后，能在控制台看到一条欢迎信息（如“Welcome to the program!”）。

STAGE_DONE: requirements

现在修改代码文件：

```json
{
  "action": "file_write",
  "args": {
    "path": "/tmp/project_20250423_114544_8f6b8f/hello_world.py",
    "content": "print('Hello World')\nprint('Welcome to the program!')"
  }
}
```