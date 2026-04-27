- **技术栈**：Python 3.10+（最新稳定版本），仅使用内置函数 `input()`、`print()`、`float()` 和 `try/except`
- **架构分层**：单文件，函数式组织
  - `get_number(prompt)`：获取用户输入并验证
  - `main()`：主流程，包含输入、计算、输出循环
- **数据库**：无需
- **关键决策**：使用 `float()` 支持小数运算，使用 `try/except ValueError` 捕获非数字输入，用 `while True` 循环让用户可连续计算

STAGE_DONE: architecture