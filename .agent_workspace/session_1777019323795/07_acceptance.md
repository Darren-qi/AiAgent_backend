### 读取文件

```python
# calculator.py 文件内容已读取

def add(a: float, b: float) -> float:
    return a + b

def subtract(a: float, b: float) -> float:
    return a - b

def multiply(a: float, b: float) -> float:
    return a * b

def divide(a: float, b: float) -> str:
    if b == 0:
        return "错误：除数不能为0"
    return a / b

# ... 完整的菜单、输入验证、主循环代码
```

### 验收检查

| 验收标准 | 检查结果 |
|---------|---------|
| 用户运行程序后可以看到运算选择菜单 | ✅ `show_menu()` 函数打印菜单 |
| 用户选择运算类型后，可以输入两个数字并得到正确结果 | ✅ 每个分支调用对应运算函数并打印结果 |
| 用户选择除法且除数为0时，程序给出错误提示而不是崩溃 | ✅ `divide()` 函数返回错误字符串，主循环打印该字符串 |
| 用户可以选择退出程序 | ✅ 选项5调用 `break` 退出循环 |

**验收结论：所有验收标准均已满足，产品验收通过。**

STAGE_DONE: acceptance