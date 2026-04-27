### 技术栈
- **语言**：Python 3.6+
- **依赖**：无第三方库，纯标准库实现
- **输入方式**：命令行交互（input/print）

### 架构设计（极简）
单文件 `calculator.py`，包含：
- `main()`：主循环，显示菜单，处理用户选择
- 四个运算函数：`add()`、`subtract()`、`multiply()`、`divide()`
- 输入验证：捕获 `ValueError` 处理非数字输入
- 除零检查：`divide()` 中判断除数为0

### 代码规范
- 函数命名：小写+下划线
- 类型提示：为函数参数和返回值添加类型注解
- 异常处理：使用 try/except 包裹输入转换

STAGE_DONE: architecture