project_create("python_calculator")
file_write(
    path="calculator.py",
    content="""#!/usr/bin/env python3
# -*- coding: utf-8 -*-

\"\"\"
简易四则运算计算器
支持：加法、减法、乘法、除法
\"\"\"


def add(a: float, b: float) -> float:
    \"\"\"加法运算\"\"\"
    return a + b


def subtract(a: float, b: float) -> float:
    \"\"\"减法运算\"\"\"
    return a - b


def multiply(a: float, b: float) -> float:
    \"\"\"乘法运算\"\"\"
    return a * b


def divide(a: float, b: float) -> float:
    \"\"\"除法运算，包含除零检查\"\"\"
    if b == 0:
        raise ValueError("除数不能为0！")
    return a / b


def get_number(prompt: str) -> float:
    \"\"\"获取用户输入的数字，包含错误处理\"\"\"
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("输入无效，请输入一个有效的数字。")


def display_menu() -> None:
    \"\"\"显示功能菜单\"\"\"
    print("\\n===== 简易计算器 =====")
    print("1. 加法")
    print("2. 减法")
    print("3. 乘法")
    print("4. 除法")
    print("5. 退出")
    print("=======================")


def main() -> None:
    \"\"\"主程序入口\"\"\"
    print("欢迎使用简易计算器！")

    while True:
        display_menu()
        choice = input("请选择功能 (1-5): ").strip()

        if choice == "5":
            print("感谢使用，再见！")
            break

        if choice not in ("1", "2", "3", "4"):
            print("无效选择，请输入1-5之间的数字。")
            continue

        # 获取两个操作数
        num1 = get_number("请输入第一个数字: ")
        num2 = get_number("请输入第二个数字: ")

        # 执行选中的运算
        try:
            if choice == "1":
                result = add(num1, num2)
                print(f"{num1} + {num2} = {result}")
            elif choice == "2":
                result = subtract(num1, num2)
                print(f"{num1} - {num2} = {result}")
            elif choice == "3":
                result = multiply(num1, num2)
                print(f"{num1} * {num2} = {result}")
            elif choice == "4":
                result = divide(num1, num2)
                print(f"{num1} / {num2} = {result}")
        except ValueError as e:
            print(f"错误: {e}")
        except Exception as e:
            print(f"发生未知错误: {e}")


if __name__ == "__main__":
    main()
"""
)

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'python_calculator'
📄 创建文件 'calculator.py'