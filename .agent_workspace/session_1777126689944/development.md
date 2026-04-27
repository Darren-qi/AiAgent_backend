```
project_create("python_calculator")
```

```
file_write(path="calculator.py", content="\"\"\"
Python 计算器程序 - 命令行版
支持加(+)、减(-)、乘(*)、除(/)四则运算
\"\"\"

def calculate(a: float, op: str, b: float) -> float:
    \"\"\"执行基本四则运算\"\"\"
    if op == '+':
        return a + b
    elif op == '-':
        return a - b
    elif op == '*':
        return a * b
    elif op == '/':
        if b == 0:
            raise ZeroDivisionError("除数不能为零！")
        return a / b
    else:
        raise ValueError(f"不支持的运算符: {op}")


def main() -> None:
    \"\"\"主循环：接收用户输入并执行计算\"\"\"
    print("=" * 40)
    print("          Python 计算器")
    print("=" * 40)
    print("支持的运算: +, -, *, /")
    print("输入 'q' 或 'quit' 退出程序\\n")

    while True:
        try:
            # 获取第一个数字
            raw = input("请输入第一个数字 (或 q 退出): ").strip()
            if raw.lower() in ('q', 'quit'):
                print("感谢使用，再见！")
                break
            a = float(raw)

            # 获取运算符
            op = input("请输入运算符 (+, -, *, /): ").strip()
            if op.lower() in ('q', 'quit'):
                print("感谢使用，再见！")
                break
            if op not in ('+', '-', '*', '/'):
                print("错误：不支持的运算符，请使用 +, -, *, /")
                continue

            # 获取第二个数字
            raw = input("请输入第二个数字 (或 q 退出): ").strip()
            if raw.lower() in ('q', 'quit'):
                print("感谢使用，再见！")
                break
            b = float(raw)

            # 执行计算
            result = calculate(a, op, b)
            print(f"\\n结果: {a} {op} {b} = {result}\\n")
            print("-" * 40)

        except ValueError:
            print("错误：请输入有效的数字！\\n")
        except ZeroDivisionError as e:
            print(f"错误：{e}\\n")
        except KeyboardInterrupt:
            print("\\n感谢使用，再见！")
            break


if __name__ == "__main__":
    main()
")
```

```
file_write(path="README.md", content="# Python 计算器

一个简单的命令行四则运算计算器，使用 Python 标准库实现。

## 功能

- 支持加 (+)、减 (-)、乘 (*)、除 (/) 运算
- 友好的错误提示（数字格式错误、除零等）
- 连续计算，无需重启
- 输入 `q` 或 `quit` 退出程序

## 运行方式

```bash
python calculator.py
```

## 使用示例

```
========================================
          Python 计算器
========================================
支持的运算: +, -, *, /
输入 'q' 或 'quit' 退出程序

请输入第一个数字 (或 q 退出): 10
请输入运算符 (+, -, *, /): +
请输入第二个数字 (或 q 退出): 5

结果: 10.0 + 5.0 = 15.0
----------------------------------------
请输入第一个数字 (或 q 退出): q
感谢使用，再见！
```
")
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'python_calculator'
📄 创建文件 'calculator.py'
📄 创建文件 'README.md'