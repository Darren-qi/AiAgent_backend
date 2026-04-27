```python
# calculator.py

def get_number(prompt: str) -> float:
    """获取用户输入并验证是否为有效数字"""
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("输入错误：请输入一个有效的数字（例如：3.14 或 -5）")

def main():
    """加法计算器主流程"""
    print("=" * 40)
    print("         🧮 简单加法计算器")
    print("=" * 40)
    print("输入 q 可随时退出程序\n")
    
    while True:
        # 获取第一个数
        first_input = input("请输入第一个数字（或输入 q 退出）：")
        if first_input.lower() == 'q':
            break
        try:
            num1 = float(first_input)
        except ValueError:
            print("输入错误：请输入一个有效的数字（例如：3.14 或 -5）")
            continue
        
        # 获取第二个数
        second_input = input("请输入第二个数字（或输入 q 退出）：")
        if second_input.lower() == 'q':
            break
        try:
            num2 = float(second_input)
        except ValueError:
            print("输入错误：请输入一个有效的数字（例如：3.14 或 -5）")
            continue
        
        # 计算并显示结果
        result = num1 + num2
        print(f"\n✅ {num1} + {num2} = {result}")
        
        # 格式化显示（如果结果是整数则显示为整数形式）
        if result == int(result):
            print(f"📝 即：{int(num1)} + {int(num2)} = {int(result)}")
        print("-" * 40)

if __name__ == "__main__":
    main()
```

STAGE_DONE: development