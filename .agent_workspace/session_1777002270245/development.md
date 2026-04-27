STAGE_DONE: development

第一批文件（核心入口和配置）：

```python
# calculator.py
"""四则运算计算器 - 核心模块"""

def add(a: float, b: float) -> float:
    """加法运算"""
    return a + b

def subtract(a: float, b: float) -> float:
    """减法运算"""
    return a - b

def multiply(a: float, b: float) -> float:
    """乘法运算"""
    return a * b

def divide(a: float, b: float) -> float:
    """除法运算，处理除零错误"""
    if b == 0:
        raise ValueError("除数不能为0")
    return a / b

# 运算符到函数的映射字典
operations = {
    '+': add,
    '-': subtract,
    '*': multiply,
    '/': divide
}
```

```python
# main.py
"""计算器入口程序"""
from calculator import operations

def get_number(prompt: str) -> float:
    """获取用户输入的数字，处理无效输入"""
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("输入无效，请输入数字。")

def get_operator() -> str:
    """获取用户输入的运算符"""
    while True:
        op = input("请输入运算符 (+, -, *, /): ").strip()
        if op in operations:
            return op
        print("无效运算符，请从 +, -, *, / 中选择。")

def main():
    """主程序流程"""
    print("=== 简单四则运算计算器 ===")
    print("支持运算: +, -, *, /")
    print("输入 'q' 退出程序\n")
    
    while True:
        try:
            num1 = get_number("请输入第一个数字: ")
            op = get_operator()
            num2 = get_number("请输入第二个数字: ")
            
            # 执行运算
            result = operations[op](num1, num2)
            print(f"结果: {num1} {op} {num2} = {result}\n")
            
        except ValueError as e:
            print(f"错误: {e}\n")
        except KeyboardInterrupt:
            print("\n程序已退出。")
            break
        
        # 询问是否继续
        again = input("继续计算？(y/n): ").strip().lower()
        if again != 'y':
            print("感谢使用，再见！")
            break

if __name__ == "__main__":
    main()
```

```python
# test_calculator.py
"""计算器单元测试"""
import unittest
from calculator import add, subtract, multiply, divide

class TestCalculator(unittest.TestCase):
    
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(add(-1, 1), 0)
        self.assertEqual(add(0, 0), 0)
    
    def test_subtract(self):
        self.assertEqual(subtract(10, 5), 5)
        self.assertEqual(subtract(0, 5), -5)
        self.assertEqual(subtract(-3, -7), 4)
    
    def test_multiply(self):
        self.assertEqual(multiply(4, 3), 12)
        self.assertEqual(multiply(-2, 5), -10)
        self.assertEqual(multiply(0, 100), 0)
    
    def test_divide(self):
        self.assertEqual(divide(10, 2), 5)
        self.assertEqual(divide(-9, 3), -3)
        self.assertEqual(divide(7, 2), 3.5)
    
    def test_divide_by_zero(self):
        with self.assertRaises(ValueError):
            divide(5, 0)

if __name__ == "__main__":
    unittest.main()
```

```markdown
# README.md
# 简单四则运算计算器

一个基于Python的命令行四则运算计算器，支持加、减、乘、除四个基本运算。

## 功能

- 加法 (+)
- 减法 (-)
- 乘法 (*)
- 除法 (/)，包含除零错误处理

## 使用方法

```bash
python main.py
```

按提示输入数字和运算符即可。

## 运行测试

```bash
python test_calculator.py
```

## 项目结构

- `calculator.py` - 核心运算逻辑
- `main.py` - 交互式命令行入口
- `test_calculator.py` - 单元测试
```

所有文件已创建完毕。

STAGE_DONE: development