# RiffCode Agent 后端 — Harness Engineering 陈述（面试版）

> 适用：面试中向外介绍个人在 AI Agent 系统上的工程实践。
> 结构：一句话定位 → 系统概览 → 四大工程支柱（执行编排 / 上下文与记忆 / 异常与可靠性 / 质量与可观测）→ 数据亮点 → 话术建议。
> 事实依据：本仓库代码与文档（overview.md / boundaries.md / README_CONTEXT.md / GOLDEN.md），数字均可回查。

---

## 0. 一句话定位

**我做的是 Agent 的 Harness Engineering：不发明新算法，而是围绕"LLM 不可靠"这个前提，把编排、上下文、记忆、异常、测试、可观测做成一套可验证的工程体系，让多轮长任务在生产环境跑得稳、跑得可解释、跑得可对账。**

系统：RiffCode 智能体后端（FastAPI + LangGraph + PostgreSQL/Redis），接收自然语言任务 → 意图识别 → 规划/执行/重规划循环 → 通过技能真实读写文件与调工具 → SSE 流式回传全过程。支持 8 家 LLM Provider 路由，生产单会话可达几十次 LLM 调用、累计 200k+ token 计费的长任务。

---

## 1. 系统概览

| 维度 | 选型/规模 |
|---|---|
| Web 框架 | FastAPI + uvicorn（异步全链路） |
| Agent 编排 | LangGraph（命令式主循环）+ 自研节点体系 |
| LLM | DeepSeek / Kimi / 智谱 / OpenAI / Anthropic / Gemini / MiniMax / Ollama，8 Provider 统一工厂 |
| 模型路由 | cost / quality / balance 三策略，按任务选模型 |
| 数据 | PostgreSQL（asyncpg 异步会话）+ Redis + Alembic 手写编号迁移 |
| 安全 | input_guard 入口守卫、output_guard 出口掩码、Docker 沙箱代码执行 |
| 前端协议 | REST + SSE（29 种事件类型），Bearer JWT |

**分层架构**（依赖单向向下，10 条可执行边界规则 R1–R10）：

```
接入层 api/        —— 协议适配：HTTP/SSE 桥、依赖注入、认证
业务层 services/   —— 用例逻辑，抛 AppException 体系
智能体层 agent/    —— graphs 编排 + nodes 节点 + context 记忆 + llm 路由 + skills 技能
安全层 security/   —— 守卫与沙箱，独立于业务层
数据层 models/db/  —— ORM + 异步会话 + 迁移
```

关键约束：`agent/` 禁止 import `api/`（编排层不感知 HTTP）；图内一切对外状态变化只能经 `on_step` 回调发出，节点内禁止构造 SSE 字符串——**编排与呈现彻底解耦**，同一套图既能服务 SSE 流也能服务同步接口。

---

## 2. 支柱一：执行编排（路径与架构）

### 2.1 执行路径

```
POST /api/v1/agent/execute/stream
 → input_guard.check(task)          # 安全前置，不过则立即 error 事件
 → ensure Session + 落 user 消息
 → event: start {task_id}
 → asyncio 后台任务执行 AgentGraph.execute()
      ├─ 意图检测 → planner 拆 todos（event: planning / todos）
      ├─ 按 todo 顺序推进 _execute_todo_with_loop()
      │    while 未完成:
      │      hook1 上下文构建 → planner.think → plan → next_moves
      │      → 技能/工具真实执行（文件落盘）
      │      → hook2 observation 登记
      │      → 失败 → replanner 重规划
      │      → LoopDetector 防自旋 → 30 轮上限裁判
      ├─ hook3 finally: on_turn_end（全量压缩唯一入口）
      └─ integrator → final_summary
 → 先落库、再推终态事件（complete/error/stopped）
```

### 2.2 工程设计点（面试可展开）

1. **命令式主循环而非声明式 DAG**：Agent 的控制流是"按 todo 推进、失败重规划、动态轮次"，声明式静态图表达不了。我把 `AgentGraph` 做成类内命令式循环，同时保留 supervisor / safety / dynamic_subgraph 三种图能力做监督决策与动态子图。
2. **step / turn 两级抽象**：turn = 一次用户请求（上下文管理的生命周期），step = 一次 think→plan→execute→observe（最小执行单元）。所有横切能力（上下文钩子、计费、循环检测）都挂在这两级上，避免散落。
3. **多层防失控**（Agent 可靠性的核心）：
   - `LoopDetector`：三类异常模式检测——同一计划重复 ≥3 次（死循环）、计划两极振荡（反复切换方案）、连续无进展 ≥3 次；检测到即终止并给出 fallback_action（回退上结果/合并末两结果），而不是让任务空转烧钱；
   - 30 轮硬上限 + `roundcap_judge`：达上限后用一次轻量 LLM 调用判断用户新消息是否"继续执行"，支持截断续跑与断点恢复（`cap_restore`）；
   - **末轮强制交付**：最后一个 todo 的最后一轮禁止再收集信息，必须产出交付物——针对"生产现场 5 轮全在读文件、从未进入产出"的真实事故设计；
   - Planner 返回空列表时降级生成默认待办，不让任务直接死。
4. **人机协作协议**：`human_input_requested` / `danger_approval_*` 等事件族支持人工介入与危险操作审批，超时有独立语义。

---

## 3. 支柱二：上下文与记忆管理

这是我认为最能体现 harness 工程深度的部分。核心问题：**长任务里上下文会爆，但粗暴截断会丢关键信息。**

### 3.1 ContextManager：三钩子 + 分级淘汰

设计成可插拔组件（策略 / 向量层 / 外部存储 / 摘要器四个插拔位），挂在图执行的三个固定钩子上：

| 钩子 | 位置 | 职责 |
|---|---|---|
| hook1 | think 之前 | 按预算**重建**本 step 上下文（JIT 按需召回，不预加载） |
| hook2 | observation 之后 | 登记新观察 + 预算记账 + step 级 masking |
| hook3 | execute() 的 finally | **全量压缩的唯一入口**（turn 结束） |

三条铁律：
1. **每个钩子都 try/except——上下文管理失败只降级、绝不阻塞任务**（降级为无上下文管理继续跑）；
2. step 级只允许 masking/索引化，**全量压缩只发生在 turn 结束**——执行中途绝不动全量历史，防止半压缩状态；
3. **任何被移除的内容必须 `external_ref` 可恢复**（或 pinned 固定保护）——淘汰不是删除。

分级策略（全部配置化，无硬编码）：
- 预算 128K（对齐 deepseek-chat 窗口，上限=触发点，杜绝 400）；
- 用满才触发压缩，压回 50%；最近 2 个 step 的观察不淘汰；turn 内超 10 step 触发长循环轨迹折叠；
- 压缩手段分层：masking（敏感/低价值字段掩码）→ 摘要（白名单只摘要）→ 卸载外部存储 → 轨迹折叠；
- 召回分层 `trigger+vector`：先规则筛候选、再算 embedding 做余弦（阈值 0.5），**query embedding 只在存在候选时才计算**，控制成本；
- `calibrate(actual, estimated)` 钩子：拿 API 真实 prompt_tokens 校准 tiktoken 估算——估算与实测闭环。

### 3.2 记忆三层

- **短期记忆**（`short_term`）：会话消息流，内存 + Postgres 双写，跨轮续读；
- **长期记忆**（`long_term`）：episode / fact 结构化存储；
- **经验库**（`experience/`）：saver / retriever / reranker 三件套，跨会话沉淀与检索（向量列规划中，二期 pgvector）。

**Postgres checkpoint**：图状态持久化到 Postgres，支撑断点续跑——任务中断（崩溃/取消/截断）后能从断点恢复而不是从头再来，这是长任务可用性的基础。

### 3.3 双口径计量（对账工程）

- `used` = **单请求真实峰值**（任意一次 LLM 调用的最大 prompt_tokens，跨轮 floor 续读）→ 用于上下文水位展示与压缩触发判断；
- `billed_in/out/cost` = **会话累计**（KV 基数 + 本 turn，跨轮累加不归零）→ 用于与 DeepSeek 后台账单对账；
- 两者刻意不同源不同口径，前端 tooltip 写明语义；会话 KV 持久化带 `cc_ver` 版本号做向后兼容读取。

---

## 4. 支柱三：异常处理机制

分四层，每层策略不同——这是 harness 的"容错预算"设计。

### 4.1 API 层：统一异常体系

- 全部业务异常继承 `AppException`（携带 `error_code` + `extra` 结构化数据），三个全局 handler 收口：
  - `AppException` → `to_dict()` 原样输出；
  - `RequestValidationError` → 422 + `details[{field,message,type}]`；
  - 裸 `Exception` 兜底 → 500（生产脱敏、开发附类型名）。
- 前端靠 `error_code` 分支处理，不解析文案。

### 4.2 SSE 流层：终态语义与顺序约定

流式接口异常不走 HTTP 状态码，转成事件：`error`（执行异常/守卫拒绝）/ `stopped`（用户中断）/ `complete`（正常）。

**关键工程约定（两次生产事故沉淀）：先落库、再推终态事件。**
前端收到 `complete` 会立即断开 SSE，后置的 await 会被 `CancelledError` 打断——所以任何"落库 + 推事件"序列必须落库在前。assistant 消息用独立协程 + 独立 DB 会话持久化，不依赖请求作用域资源（请求结束资源已释放）。

### 4.3 Agent 运行层：降级铁律

**非关键路径失败只降级、绝不阻塞任务执行**——在代码里是 12+ 处显式落地的模式，不是口号：

| 降级点 | 失败后行为 |
|---|---|
| ContextManager 初始化/三钩子 | 降级为无上下文管理，任务照跑 |
| usage 计费追踪 | 跳过追踪，不影响 LLM 调用返回 |
| run 日志打点 | 不落盘，调用照常 |
| 用户 API key 装载 | 回落系统 key |
| 用量续读（会话 KV） | 降级为 0 |
| Planner 空待办 | 降级生成默认待办 |
| 断点保存 | best-effort，不阻塞报错返回 |

与之相对的是**关键路径 fail-fast**：安全守卫拒绝、认证失败必须立即终止。哪些能降级、哪些必须拦，是显式设计过的。

### 4.4 执行层：受控失败恢复

- 节点失败 → replanner 带着 `last_error` 重规划（下一轮思考必须引用错误并重试原动作，不许绕圈烧轮次——有测试用例钉死这个行为）；
- LoopDetector 终止 + fallback_action 兜底；
- 异常中断同样记失败标记、保留断点（best-effort），支撑"失败后可续跑"；
- `AppException` 之外，Agent 内部吞异常返回 `success=False` 的结果 dict，由端点侧决定落库 `failed` 与推 `error`——**图内不抛协议异常**，保持编排层纯净。

---

## 5. 支柱四：质量工程与可观测

### 5.1 黄金测试门禁（Golden Gate）

- 场景化测试集：`TESTCASES.md` 15 个场景、68 条用例（人话版场景清单），发现新问题**先补用例再修**（先红后绿），用例永久保留；
- `run_golden.py` 统一门禁：退出码 0 = 无新增失败；`--fast` 跳过真实 LLM 做提交前快验；
- 豁免唯一入口 `golden_allowlist.txt`，每条必写原因，**清单只能变短**——禁止为过门禁随手加豁免；
- 每次改动跑全量，不允许只跑"觉得相关"的子集——防止修一个坏三个；
- 图/提示词/技能改动额外跑 `scripts/smoke/` 7 个真实链路场景（锚定/批量创建/SSE/路径修复等）。

### 5.2 可观测（四轨并行）

1. loguru 文本日志：request_id 贯穿 + 每次 LLM 调用打点（model/provider/latency/prompt_tokens/cost）；
2. `execution_nodes` 落库：执行步骤持久化，可回查；
3. JSONL run 日志（`logs/runs/*.jsonl`）：每次运行完整事件流，可离线分析（我做过：用它统计单次调用峰值 vs 会话累计，验证计费口径自洽）；
4. SSE `context_usage` 实时事件：上下文水位 / 压缩次数 / 计费三元组推给前端，生产现场直接可见。

### 5.3 边界与演进（诚实项，面试加分）

主动暴露而非隐瞒：
- endpoints 层存量 ~20 处裸 `HTTPException` 正逐步迁到 `AppException`（有完整清单文档）；
- `endpoints/agent.py` 是 1100+ 行"厚端点"，新逻辑持续下沉到 `agent/`；
- 依赖唯一来源已收敛到 `pyproject.toml`（清掉了 Flask 时代的 requirements.txt 漂移）；
- 工具层 Harness 升级在途：生产高频"工具传参错误"（连续 5 次缺 path），方向是消费 `params_invalid` 标记做前置拦截——**评估过开放 shell 命令替代结构化工具，结论是不换**：传参错误是模型构造问题，shell 参数更多更易错，且会击穿基于"工具有限枚举"设计的授权/路径牢笼/审计三层安全。

---

## 6. 数据亮点（面试可引用的量化事实）

- **8 家 Provider 统一工厂 + 3 策略路由**，按 cost/quality/balance 选型，用户级 API key 按 session→user 装载、失败回落系统 key；
- **29 种 SSE 事件**构成完整的执行过程可视化协议；
- **128K 预算、1.0 触发 / 0.5 压回**的上下文策略，22 条上下文专项测试覆盖 9 个必测用例（常驻项恒在/最近 N 步保护/压缩只在 turn 后/按 ref 恢复等）；
- **LoopDetector 三类死循环模式** + 30 轮硬上限 + 末轮强制交付，多层防失控；
- **黄金门禁 68 条用例**，基线从"建集前 23 failed + 27 errors"清零到门禁化管理；
- 降级点 12+ 处显式落地；`先落库再推终态` 等约定均有生产事故复盘支撑；
- 生产实测：单会话 40+ 次 LLM 调用、累计 ~200k token 计费的长任务稳定跑完，上下文单请求水位与累计计费双口径可对账。

---

## 7. 面试话术建议

**开场（30 秒）**：
> "我这个项目的核心工作是 Agent 的 harness engineering。LLM 本身不可靠——会漏参数、会原地自旋、上下文会爆、异常路径多。我的工作是把这些不可靠性用工程手段包住：编排层做多层防失控，上下文层做分级淘汰加可恢复，异常层区分降级和 fail-fast，质量层用黄金门禁钉死回归。"

**被追问某一块时的展开顺序**：问题现场 → 设计决策 → 落地的硬约束（铁律/测试）→ 生产验证。例如讲上下文：
> "现场是长任务上下文爆掉。我做了三钩子的 ContextManager，关键决策有三个：压缩只在 turn 结束做（执行中途不做全量淘汰）、被淘汰的内容必须可恢复（external_ref）、整个组件失败只降级不阻塞。这三条都有测试钉着。"

**收尾（体现方法论）**：
> "我沉淀了一套原则：非关键路径降级、关键路径 fail-fast；先落库再推终态；新问题先补用例再修；豁免清单只能变短。这些不是文档里的口号，是代码里 12 处降级点、68 条用例和门禁退出码在执行。"

---

## 附：关键文件索引（被追问时快速定位）

| 关注点 | 位置 |
|---|---|
| 分层与边界规则 R1–R10 | `docs/architecture/boundaries.md` |
| 架构总览与时序图 | `docs/architecture/overview.md` |
| ContextManager 三钩子/配置/扩展点 | `README_CONTEXT.md`、`app/agent/context/` |
| 主循环与降级点 | `app/agent/graphs/main_graph.py` |
| LoopDetector / 执行状态 | `app/agent/state.py` |
| 30 轮上限与断点续跑 | `app/agent/roundcap_judge.py` |
| 异常体系 | `app/core/exceptions.py`、`app/main.py` handler |
| 记忆三层 | `app/agent/memory/{short_term,long_term,manager,pgsaver}.py` |
| LLM 路由与计费 | `app/agent/llm/{factory,router,budget_manager}.py` |
| 黄金门禁 | `run_golden.py`、`tests/GOLDEN.md`、`tests/TESTCASES.md` |
| 工具层升级在途项 | `docs/plans/tool-harness-upgrade.md` |
