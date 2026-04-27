```python
# calculator.py

def add(a: float, b: float) -> float:
    """返回两个数字的和"""
    return a + b


def main():
    print("=== 简单加法计算器 ===")
    print("输入 'q' 退出程序\n")

    while True:
        try:
            num1_str = input("请输入第一个数字: ")
            if num1_str.lower() == 'q':
                print("感谢使用，再见！")
                break

            num2_str = input("请输入第二个数字: ")
            if num2_str.lower() == 'q':
                print("感谢使用，再见！")
                break

            num1 = float(num1_str)
            num2 = float(num2_str)

            result = add(num1, num2)
            print(f"{num1} + {num2} = {result}\n")

        except ValueError:
            print("❌ 输入错误：请输入有效的数字！\n")


if __name__ == "__main__":
    main()
```

STAGE_DONE: development