```bash
project_create("hello_world")
```

```bash
file_write(path="hello.py", content="# Hello World Program
# A simple program that prints \"Hello World\" to the console

def main():
    \"\"\"Main function that prints the greeting.\"\"\"
    print(\"Hello World\")

if __name__ == \"__main__\":
    main()
")
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'hello_world'
📄 创建文件 'hello.py'