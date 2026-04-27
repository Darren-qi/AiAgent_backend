### 技术栈选择
- **语言**: Python 3.8+
- **输入处理**: Python内置`input()`函数
- **无第三方库依赖**

### 架构分层（单文件内）
- **交互层**: 菜单显示、用户输入获取
- **业务逻辑层**: 四则运算函数（加、减、乘、除）
- **主控层**: 循环控制、异常处理

### 代码规范
- 函数名使用蛇形命名法（`snake_case`）
- 常量使用全大写（如`PROMPT_MENU`）
- 添加类型注解
- 除数为0时抛出`ValueError`异常

### 文件结构
```
calculator_app/
└── calculator.py      # 主程序文件
```

STAGE_DONE: architecture