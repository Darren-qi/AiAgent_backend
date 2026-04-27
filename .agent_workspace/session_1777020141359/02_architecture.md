- **技术栈**：Python 3.9+，仅使用内置函数 `input()`、`print()`、`float()`、异常处理
- **代码结构**：单文件 `calculator.py`，包含：
  - `main()`：主循环，处理持续交互
  - `calculate()`：执行加法运算与错误处理
- **设计决策**：使用 `while True` 循环实现持续运行，通过 `try/except` 捕获非数字输入，退出指令用 `q` / `exit` 触发 `break`

STAGE_DONE: architecture