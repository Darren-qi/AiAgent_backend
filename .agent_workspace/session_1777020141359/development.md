project_create("python_addition_calculator")
file_write(path="calculator.py", content="""#!/usr/bin/env python3
# -*- coding: utf-8 -*-

\"\"\"一个简单的加法计算器 - 支持持续交互和错误处理\"\"\"

def calculate(num1: float, num2: float) -> float:
    \"\"\"执行加法运算\"\"\"
    return num1 + num2

def main():
    \"\"\"主交互循环\"\"\"
    print("=== 简单加法计算器 ===")
    print("输入 'q' 或 'exit' 退出程序\\n")

    while True:
        # 获取第一个数字
        first_input = input("请输入第一个数字: ").strip()
        if first_input.lower() in ('q', 'exit'):
            print("感谢使用，再见！")
            break

        try:
            num1 = float(first_input)
        except ValueError:
            print("请输入有效数字！\\n")
            continue

        # 获取第二个数字
        second_input = input("请输入第二个数字: ").strip()
        if second_input.lower() in ('q', 'exit'):
            print("感谢使用，再见！")
            break

        try:
            num2 = float(second_input)
        except ValueError:
            print("请输入有效数字！\\n")
            continue

        # 计算结果并显示
        result = calculate(num1, num2)
        print(f"{num1} + {num2} = {result}\\n")

if __name__ == "__main__":
    main()
""")
STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'python_addition_calculator'
📄 创建文件 'calculator.py'