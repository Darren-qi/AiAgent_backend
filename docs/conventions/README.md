# 编码规范（LangGraph 后端）

> 本文是代码风格与工程约定的单一出处；规则均与当前仓库实际代码对齐
> （ruff/mypy 配置取自 `pyproject.toml`，示例取自现有实现）。
> 关联：测试规范 [testing.md](testing.md)｜模块边界 [../architecture/boundaries.md](../architecture/boundaries.md)。

## 1. 语言与工具链

| 项 | 约定 |
|---|---|
| Python 版本 | ≥3.10（`requires-python = ">=3.10"`，本地 venv 3.11） |
| 格式/静态检查 | ruff：`line-length = 100`，`target-version = "py310"` |
| ruff 规则集 | `select = ["E","F","W","I","N","UP","B","C4"]`，`ignore = ["E501"]` |
| 类型检查 | mypy（`[tool.mypy]`，渐进式，新代码优先补注解） |
| 测试 | pytest，`asyncio_mode = "auto"`（异步测试函数无需装饰器） |
| 注释/文档语言 | **中文**（docstring、行内注释、commit message、本文档体系） |

## 2. 命名规范

| 对象 | 约定 | 示例 |
|---|---|---|
| 模块/函数/变量 | snake_case | `get_settings`、`execute_task`、`session_id` |
| 类 | PascalCase | `AgentGraph`、`ContextManager`、`AppException` |
| 异常类 | 语义后缀 + `Exception` | `TokenExpiredException`、`NotFoundException` |
| 私有/内部 | 前缀 `_` | `_history_note`、`_finalize_db_task`、`_execute_unified` |
| 常量 | UPPER_SNAKE | `STREAM_DONE`、模块级守卫实例 `input_guard` |
| Provider/策略/技能类 | 名称后缀点明角色 | `DeepSeekProvider`、`BalanceRouter`、`FileOperationsSkill` |
| 工厂函数 | `build_*` / `get_*` | `build_context_config`、`get_settings` |
| 测试 | `test_*` / `Test*` | `test_file_operations`、`TestAgentGraph` |
| 路由端点函数 | 动词短语 | `execute_task_stream`、`create_session` |
| 文件名 | 与模块职责同名 snake_case | `task_executor.py`、`progressive_loader.py` |

## 3. 目录组织约定

```
app/
├── main.py            # 只做装配：中间件/路由/异常 handler，不写业务
├── core/              # 配置、异常定义、JWT —— 无业务、无 HTTP 路由
├── api/
│   ├── deps.py        # 依赖注入（认证、DB 会话）
│   ├── v1/endpoints/  # 一域一文件：agent.py、auth.py、users.py…
│   └── v1/schemas/    # 端点级请求/响应模型，与 endpoints 同名对应
├── schemas/           # 业务级模型（user/post/token/common），与 api/v1/schemas 分层
├── services/          # 用例逻辑，一域一文件
├── models/            # ORM 表映射，一表一文件
├── db/                # base.py（Mixin 集中）+ session.py（引擎/会话）
├── agent/             # 智能体子系统，按能力域分子包（见边界文档 §2.3）
├── security/          # 守卫与沙箱
└── utils/             # logger/cache 等横切工具
```

- **schemas 与 models 分离**：Pydantic（协议）≠ ORM（存储），禁止混用同一类；
- **一文件一职责**：角色/节点/技能类均单文件，工厂函数 `build_*` 收口构造；
- **技能结构**：`skills/<name>/{skill.py, SKILL.md}`，SKILL.md 供渐进式加载。

## 4. 注释与文档规范

1. 每个 `.py` 文件首行 docstring：**一句话职责**；关键文件附"铁律/禁令"；
2. 中文注释优先写**为什么**（决策依据、踩坑日期、生产现场），而非复述代码；
3. 事故复盘式注释是本仓库惯例，格式参照：

   ```python
   # 原先任务记录创建时写 status='running' 后再没人更新过，导致所有任务
   # 永远停在 running（2026-11-09 实测：任务18 报错却 status=completed）
   ```

4. 跨文件契约（如"先落库再推事件"）要在**两端**都写注释，指明对方；
5. 需求/方案级文档落 `docs/` 或 `README_*.md`，不在代码里写长篇设计。

## 5. 错误处理规范

1. **业务异常一律用 `AppException` 子类**（`app/core/exceptions.py`），携带
   `error_code`；新增错误码先登记 `docs/reference/error-codes.md`：

   ```python
   raise NotFoundException(resource="文章", resource_id=post_id)
   raise InvalidCredentialsException()
   ```

2. **禁止裸 `except:`**；只捕获具体异常（`OSError`/`ValueError`/`CancelledError`…），
   必须 `# noqa: BLE001` 说明为何吞掉；
3. **降级不阻塞**：上下文管理、历史拼装、落库兜底等非关键路径 `try/except` 后记日志继续
   （`[CtxMgr] on_step_start 失败（不阻塞）` 是范例）；
4. **`CancelledError` 单独处理**并放在 `Exception` 捕获之前（它是 `BaseException` 子类，
   但业务代码常显式 re-raise）；
5. Pydantic 校验失败由全局 handler 统一转 422，端点内不要手动重复校验格式类字段；
6. endpoint 存量 `raise HTTPException` 允许存在，**新代码不得再引入**（逐步迁移）。

## 6. 配置规范

三层结构，读配置永远走 `get_settings()`：

| 层 | 文件 | 内容 |
|---|---|---|
| 1 环境变量 | `.env`（模板 `.env.example.zh-CN`） | LLM key、数据库 URL、预算阈值等密钥与环境差异 |
| 2 开发默认值 | 根 `config.py`（gitignored） | `load_dotenv()` 后的本地默认 dict |
| 3 类型化配置 | `app/core/config.py` | `Settings(BaseSettings)` + `Field` 校验 + `@property` 派生；`get_settings()` 用 `lru_cache` 单例 |

- 新配置项：加 `Settings` 字段 + 默认值 + 中文注释，需要时同步 `.env.example.zh-CN`；
- 有语义约束的值用 `Field(pattern=...)` / 枚举约束；
- **密钥纪律**：key 只从 `.env` 读，不进日志、不进异常消息、不进文档；
- 派生配置用方法收口（如 `build_context_config()`），调用方不手拼字典。

## 7. 数据库与迁移

1. ORM 基类统一继承 `db/base.py` 的 `IDMixin`/`TimestampMixin`/`SoftDeleteMixin`；
2. 新表/字段 → 手写迁移 `alembic/versions/00N_描述.py`（编号递增，不用 hash）；
   辅助脚本 `scripts/migrate.sh`；
3. 用 `async with AsyncSessionLocal() as s:` 显式提交；只读查询后 `rollback()` 归还连接；
4. 状态回写注意"最终状态"语义（`_finalize_db_task`：已完成不被覆盖为 failed）。

## 8. SSE / 流式约定

1. 事件格式：`event: {name}\ndata: {json}\n\n`；事件名是名词/动词短语（`todos`、
   `todo_start`、`final_summary`）；
2. 图内状态变化只经 `on_step(step_type, data)`，由端点翻译，**节点不拼 SSE 字符串**；
3. **先落库、再推终态事件**（`complete`/`error`/`stopped` 之后才允许结束流）；
4. 终态事件每个流只发一次；断连/abort 只发 `stopped`，不补 `complete`；
5. 30s 空闲发 `heartbeat`；`X-Accel-Buffering: no` 禁用反代缓冲。

## 9. 提交与迭代

- commit message 中文，惯例前缀 `update:` / `fix:` / `init`（见 git log）；
- 修 bug 先补黄金测试用例（先红后绿），见 [testing.md](testing.md)；
- 涉及图/提示词/技能的改动，除单测外跑 `scripts/smoke/` 真实链路冒烟。
