**技术栈选择：**
- 语言：Python 3
- 框架：无（标准库即可）
- 依赖：无第三方库

**架构设计：**
- 单文件脚本 `calculator.py`
- 使用 `input()` 获取用户输入
- 使用 `float()` 或 `int()` 转换输入类型
- 使用 `try/except` 处理非数字输入异常
- 使用 `print()` 输出结果

**关键设计决策：**
- 无数据库、无缓存、无消息队列
- 不涉及微服务划分
- 代码规范：遵循PEP8，函数命名使用snake_case

STAGE_DONE: architecture