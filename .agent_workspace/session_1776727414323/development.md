project_create("simple_python_calculator")
file_write(path="calculator.py", content="""#!/usr/bin/env python3
"""
简单的Python计算器
支持加、减、乘、除四种基本运算
"""

def display_menu():
    """显示计算器菜单"""
    print("\\n=== 简单计算器 ===")
    print("支持的运算:")
    print("  + : 加法")
    print("  - : 减法")
    print("  * : 乘法")
    print("  / : 除法")
    print("  q : 退出程序")
    print("==================")

def get_number_input(prompt):
    """获取用户输入的数字"""
    while True:
        try:
            value = input(prompt)
            if value.lower() == 'q':
                return None
            return float(value)
        except ValueError:
            print("错误：请输入有效的数字！")

def get_operator_input():
    """获取用户输入的运算符"""
    valid_operators = ['+', '-', '*', '/', 'q']
    while True:
        operator = input("请输入运算符 (+, -, *, /) 或输入 'q' 退出: ").strip()
        if operator in valid_operators:
            return operator
        print("错误：请输入有效的运算符 (+, -, *, /) 或 'q' 退出！")

def calculate(num1, num2, operator):
    """执行计算并返回结果"""
    try:
        if operator == '+':
            return num1 + num2
        elif operator == '-':
            return num1 - num2
        elif operator == '*':
            return num1 * num2
        elif operator == '/':
            if num2 == 0:
                raise ZeroDivisionError("除数不能为零！")
            return num1 / num2
    except ZeroDivisionError as e:
        return str(e)
    except Exception as e:
        return f"计算错误: {str(e)}"

def main():
    """主程序"""
    print("欢迎使用简单计算器！")
    
    while True:
        display_menu()
        
        # 获取第一个数字
        num1 = get_number_input("请输入第一个数字 (或输入 'q' 退出): ")
        if num1 is None:
            print("感谢使用，再见！")
            break
        
        # 获取运算符
        operator = get_operator_input()
        if operator == 'q':
            print("感谢使用，再见！")
            break
        
        # 获取第二个数字
        num2 = get_number_input("请输入第二个数字 (或输入 'q' 退出): ")
        if num2 is None:
            print("感谢使用，再见！")
            break
        
        # 执行计算
        result = calculate(num1, num2, operator)
        
        # 显示结果
        print(f"\\n计算结果: {num1} {operator} {num2} = {result}")
        
        # 询问是否继续
        continue_calc = input("\\n是否继续计算？(y/n): ").strip().lower()
        if continue_calc != 'y':
            print("感谢使用，再见！")
            break

if __name__ == "__main__":
    main()
""")

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'simple_python_calculator'
📄 创建文件 'calculator.py'