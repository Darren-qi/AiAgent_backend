### 需求文档

**功能清单：**
1. 用户输入两个数字
2. 程序计算并显示两数之和
3. 友好的交互提示

**验收标准：**
- 用户可以启动程序并看到输入提示
- 用户输入两个数字后，程序正确输出它们的和
- 程序能处理整数和小数输入

---

### 代码生成

```python
# 简单的加法计算器

def add_calculator():
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
```

STAGE_DONE: requirements