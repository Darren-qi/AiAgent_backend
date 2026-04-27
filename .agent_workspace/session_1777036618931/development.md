project_create("python_calculator")
file_write(path="calculator.py", content="""#!/usr/bin/env python3
# -*- coding: utf-8 -*-

\"\"\"
Python计算器 - 安全表达式求值
使用ast模块替代eval()，防止代码注入
\"\"\"

import ast
import operator
import sys


# 支持的操作符映射
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}


def safe_eval(expression: str) -> str:
    \"\"\"安全地计算数学表达式，返回字符串结果\"\"\"
    try:
        # 解析表达式为AST
        tree = ast.parse(expression.strip(), mode='eval')
        # 计算AST节点值
        result = _eval_node(tree.body)
        # 格式化结果：整数不显示小数点，浮点数保留合理精度
        if isinstance(result, float):
            if result == int(result):
                return str(int(result))
            # 避免浮点数精度问题
            return f"{result:.10f}".rstrip('0').rstrip('.')
        return str(result)
    except ZeroDivisionError:
        return "错误：不能除以0"
    except SyntaxError:
        return "错误：表达式语法不正确"
    except (ValueError, TypeError):
        return "错误：输入格式有误"
    except Exception as e:
        return f"错误：{str(e)}"


def _eval_node(node) -> float:
    \"\"\"递归计算AST节点值\"\"\"
    if isinstance(node, ast.Constant):
        # Python 3.8+ 使用 ast.Constant
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
    elif isinstance(node, ast.Num):  # 兼容旧版本Python
        return float(node.n)
    elif isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        op_type = type(node.op)
        if op_type not in OPERATORS:
            raise ValueError(f"不支持的操作符: {op_type.__name__}")
        # 除法检查
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise ZeroDivisionError()
        return OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        # 支持一元负号
        if isinstance(node.op, ast.USub):
            return -_eval_node(node.operand)
        elif isinstance(node.op, ast.UAdd):
            return _eval_node(node.operand)
        raise ValueError(f"不支持的一元操作符: {type(node.op).__name__}")
    else:
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


def print_banner():
    \"\"\"打印欢迎信息\"\"\"
    print("=" * 40)
    print("      Python 安全计算器")
    print("=" * 40)
    print("支持的运算: +, -, *, /, //, %, **")
    print("输入 'exit' 或 'quit' 退出")
    print("输入 'help' 查看帮助")
    print("=" * 40)


def print_help():
    \"\"\"打印帮助信息\"\"\"
    print("\\n使用说明：")
    print("  - 直接输入数学表达式，如: 2 + 3 * 4")
    print("  - 支持括号: (2 + 3) * 4")
    print("  - 支持小数: 3.14 * 2")
    print("  - 支持负号: -5 + 3")
    print("  - 支持幂运算: 2 ** 3")
    print("  - 支持取模: 10 % 3")
    print("  - 支持整除: 10 // 3")
    print("  - 输入 'exit' 退出程序\\n")


def main():
    \"\"\"主交互循环\"\"\"
    print_banner()
    
    while True:
        try:
            user_input = input("\\n请输入表达式: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\\n\\n感谢使用，再见！")
            sys.exit(0)
        
        if not user_input:
            continue
        
        # 退出命令
        if user_input.lower() in ('exit', 'quit', 'q'):
            print("感谢使用，再见！")
            break
        
        # 帮助命令
        if user_input.lower() == 'help':
            print_help()
            continue
        
        # 计算并输出结果
        result = safe_eval(user_input)
        print(f"结果: {result}")


if __name__ == "__main__":
    main()
""")

file_write(path="README.md", content="""# Python 安全计算器

一个使用Python标准库 `ast` 模块实现的命令行计算器，支持安全的数学表达式求值。

## 功能特性

- 基本四则运算：加 (+)、减 (-)、乘 (*)、除 (/)
- 扩展运算：整除 (//)、取模 (%)、幂运算 (**)
- 支持括号改变运算优先级
- 支持小数和负数
- 安全的表达式求值（不使用 `eval()`）
- 友好的错误提示（除零、语法错误等）

## 使用方法

```bash
python calculator.py
```

### 示例

```
请输入表达式: 2 + 3 * 4
结果: 14

请输入表达式: (2 + 3) * 4
结果: 20

请输入表达式: 10 / 3
结果: 3.3333333333

请输入表达式: 10 / 0
结果: 错误：不能除以0

请输入表达式: exit
感谢使用，再见！
```

## 技术栈

- Python 3.8+
- 标准库：`ast`, `operator`, `sys`

## 安全设计

使用 `ast` 模块将表达式解析为抽象语法树，然后手动遍历节点进行求值，避免了 `eval()` 可能带来的代码注入风险。
""")

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'python_calculator'
📄 创建文件 'calculator.py'
📄 创建文件 'README.md'