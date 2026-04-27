### 技术选型
- **语言**：Python 3.8+
- **外部依赖**：无（纯标准库实现）
- **输入处理**：`input()` + `float()` 转换
- **异常处理**：`try/except ValueError`

### 架构分层（单文件）
```
- 用户交互层：input()/print() 输入输出
- 业务逻辑层：加法运算
- 异常处理层：输入校验
```

### 代码规范
- 函数命名：小写+下划线（`add_calculator`）
- 主入口：`if __name__ == "__main__":`
- 异常捕获：只捕获预期异常类型
- 输出格式：清晰显示运算式

STAGE_DONE: architecture