- **技术栈**：Python 3.8+，使用 `akshare` 获取数据，`openpyxl` 写入Excel
- **架构**：单文件脚本，按函数分模块：数据获取 → 数据清洗 → Excel导出
- **数据库**：不需要
- **关键设计**：异常处理优先使用akshare，失败时降级为模拟数据，确保功能可演示

STAGE_DONE: architecture