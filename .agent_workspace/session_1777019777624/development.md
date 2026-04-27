```
project_create("python_add_calculator")
```

```
file_write(
    path="calculator.py",
    content="""# 简单的加法计算器

def add_calculator():
    \"\"\"加法计算器主函数\"\"\"
    print("=== 简单的加法计算器 ===")
    
    try:
        # 获取用户输入
        num1 = float(input("请输入第一个数字: "))
        num2 = float(input("请输入第二个数字: "))
        
        # 计算和
        result = num1 + num2
        
        # 输出结果
        print(f"{num1} + {num2} = {result}")
        
    except ValueError:
        print("输入错误：请输入有效的数字！")

if __name__ == "__main__":
    add_calculator()
"""
)
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'python_add_calculator'
📄 创建文件 'calculator.py'