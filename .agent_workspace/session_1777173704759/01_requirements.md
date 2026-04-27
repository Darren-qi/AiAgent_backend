### 需求文档：AST API框架

**项目概述**：构建一个基于AST（抽象语法树）的API框架，采用分层架构（Controller/Service/DAO），集成MySQL和Doris数据库连接工具，支持SQL解析和通用查询能力。

---

### 功能清单
1. **分层架构**：Controller（API层）+ Service（业务层）+ DAO（数据访问层）
2. **数据库连接工具**：MySQL连接池 + Doris连接池（基于JDBC）
3. **AST解析引擎**：支持SQL解析为AST树结构
4. **通用查询API**：通过AST节点生成并执行SQL查询
5. **配置管理**：数据库连接配置通过YAML/JSON文件管理

---

### 验收标准（用户视角）
- 用户可以启动服务，并调用 `/api/parse` 接口传入SQL，返回AST树结构
- 用户可以调用 `/api/query` 接口传入AST节点参数，框架自动生成SQL并查询MySQL或Doris，返回结果
- 用户可以通过配置文件切换MySQL和Doris数据源，无需重启服务
- 用户可以查看项目目录结构，明确区分 controller/service/dao 三层
- 用户调用接口时有明确的错误提示和日志输出

---

STAGE_DONE: requirements