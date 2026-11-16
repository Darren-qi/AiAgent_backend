# 工具层 Harness 化优化计划（LangGraph 后端）

> 状态：**计划定稿待执行**（2026-11-16 制定）
> 背景：生产高频"工具传参错误"（TC-S16-04 连续 5 次缺 path）；经三路调研 + AutoGen 后端对照，
> 确认当前是"轻量自研工具层（Harness 雏形）"——6 条 Harness 标准中白名单/强校验/自动重试/热插拔缺失。
> 蓝本：AutoGen 后端 `security/authorizer.py`（RunGuard + TOOL_REGISTRY + 结构化拒绝）三件套，
> **适配而非照搬**——LG 技能是 SKILL.md + 文本协议，不迁 `@tool` 装饰器形态。
> 配套：[current-sprint.md](current-sprint.md)｜[../conventions/testing.md](../conventions/testing.md)（黄金铁律全程适用）

## 0. AutoGen 机制适用性评估（搬运清单）

| AutoGen 机制 | 处置 | 落点 |
|---|---|---|
| `TOOL_REGISTRY` + `ToolMeta`（risk/path_arg/url_arg） | ✅ 搬 | `SkillMetadata` 扩 frontmatter 字段 + 注册中心过滤 API |
| `RunGuard.begin/finish` 执行前检查点 | ✅ 搬 | 新建 `app/agent/skills/guard.py`，挂 `progressive_loader.execute` L5 位 |
| 工具级连续失败熔断（≥2 拒第 3） | ✅ 搬 | 与现有"同 call_key≥3"（调用级）并存互补 |
| 结构化拒绝 JSON + error_code | ✅ 搬 | `SkillResult.error` 升级为 `error_code` 协议；correction 触发改 code 匹配 |
| `safe_path`/`safe_url` 原子约束 | 🔶 收口 | LG 路径锚定散在 skill 内 → 收口 `constraints.py`；safe_url 随 http_client 补 |
| 风险分级 + 审批门 | 🔶 降级搬 | 一期只上 `risk` 分级 + `APPROVAL_MODE=auto` 配置钩子；interactive 审批二期（需 HITL 桥） |
| 角色级白名单 | 🔶 翻译 | 无多角色 → **stage 阶段白名单**（规划期只读 / 执行期全量） |
| JSONL run 日志（logs/runs） | ✅ 参考 | 阶段六 Trace 闭环参考 |
| `@tool` 装饰器 / 集中 selector | ❌ 不搬 | 形态不适配（技能更重）/ 属多智能体编排 |

## 0.5 三个先行快改点（二次确认 2026-11-16）

> 前期调研按性价比筛出的三个高回报修复点，**已逐条重新 grep 复核，全部属实**。
> 它们分别对应阶段一/二/六的核心项，可作为快改**提前单独执行**（不等整阶段排期），
> 每条改动面小、风险低、直接打击"传参错误 + 排障难"两个痛点。

| # | 快改点 | 复核证据（2026-11-16） | 归属阶段 | 改动面 |
|---|---|---|---|---|
| 1 | **消费 `params_invalid` 标记**：planner 解析层已判坏参数，但仅赋值（`planner.py:929-930`），全仓唯一消费方是测试断言；`main_graph` 生产路径 0 处读取 → 坏计划白跑一次执行往返才被 L5 拦 | grep `params_invalid`：app/ 生产代码只有赋值点，无读取点 | **阶段一**（核心项） | 极小：planner 结果透传 + main_graph 拦截分支，~20 行 |
| 2 | **`operation_targets` 契约推广到全部 9 个技能**：仅 `file_operations/SKILL.md` 声明；其余 8 个（code_generator/data_processor/general_response/http_client/notification/sandbox/search/search_files）执行前**完全放行**，缺参只能穿透到 skill 内手工 if 烧一轮 | grep `operation_targets`：仅 file_operations/SKILL.md + loader 解析器；技能目录数 = 9 | **阶段二**（核心项） | 中：8 份 SKILL.md frontmatter 各补契约（可先只读/高频技能，再补全） |
| 3 | **工具执行统一计时 + LLM 层打点**：主循环/loader 无任何 `duration/perf_counter`；`app/agent/llm/**` logger 调用数 = 0——8 个 provider 全都算好 `latency_ms` 装进 `LLMResponse` 即丢，数据有产出无出口。排"为什么慢/为什么错"只能翻库对 `created_at` 时间戳 | grep 计时：主链 0 处；grep logger in llm/：0 条；grep latency_ms：8 处 provider 均计算后仅存字段 | **阶段六**（核心项） | 小：guard/loader 包一层计时 + factory 一条 log + latency 进日志，~30 行 |

**执行建议**：快改 1、2 合并为一个"传参错误速效包"先行落地（合计 <1 天，含测试），
快改 3 并入阶段六首日；三者均须遵守黄金铁律（先补 TESTCASES 用例 → 全量门禁绿 → 文档同步）。

## 1. 目标与成功标准

**总目标**：把工具层从"文本协议 + 手工 if"升级为"注册中心 + 守卫检查点 + 结构化错误 + 可观测"的 Harness，
结构性消灭传参类错误。

| 六条标准 | 现状 | 目标 |
|---|---|---|
| 1 统一注册中心 | ◐ 40%（静态索引，1/9 技能有契约） | 9/9 技能全字段（risk/timeout/retry/stage/operation_targets/usage） |
| 2 动态白名单 | ✗ 10%（全量注入） | stage 过滤生效 + risk 分级可配 |
| 3 容错闭环 | ◐ 50%（重试是死代码） | 工具级熔断 + 瞬态重试接线 + 结构化回注 |
| 4 零歧义 Schema | ✗ 25%（字符串关键字协议） | 执行前强校验（类型/必填/未知键）+ error_code 协议 |
| 5 全链路 Trace | ◐ 40%（无耗时/LLM 归因） | 每次调用有 duration + guard 审计 + LLM 打点 |
| 6 热插拔 | ✗ 15%（API 无调用方） | register_executor 接线 + mtime 失效重载 |

**全程铁律**（见 testing.md）：每阶段先补黄金用例（先红后绿）→ 全量 `run_golden.py` 退出码 0 →
同步 TESTCASES + 本计划勾选 → 涉及提示词的改动额外跑 `scripts/smoke/`。

## 2. 分阶段实施

### 阶段一 · 结构化错误协议 + 拦截前移（P0，估 1~2 天）

> 直接打击传参错误：坏参数在解析层就被拦，错误以机器可读协议回注。

1. **消费死标记**：`planner._parse_planning_response` 的 `params_invalid`（planner.py:927-930）
   传回 main_graph——为真时**不进执行**，直接生成结构化 `last_error` 走 correction（省一次执行往返）；
2. **error_code 协议**：`SkillResult.error` 增加 `error_code` 字段，首批枚举：
   `MISSING_PARAM / INVALID_TYPE / UNKNOWN_KEY / TRUNCATED_JSON / UNKNOWN_SKILL / PATH_ESCAPE / TIMEOUT / EXEC_FAILED`；
   loader 结构化拦截（progressive_loader.py:385-390）与 skill 内缺参报错统一改写；
3. **correction 触发改协议**：`plan_action_with_feedback`（planner.py:742-761）优先按
   `error_code` 分支给修正策略与 JIT schema 注入，字符串关键字匹配降为兜底（兼容期保留）；
4. **错误码登记**：`docs/reference/error-codes.md` 增"工具层错误码"章节。

**验收**：`test_planner_params_guard.py` 扩例——params_invalid 被拦截不执行、error_code 正确回注、
correction 按 code 触发（不依赖文案）；黄金门禁全绿。

### 阶段二 · 统一注册中心强化（P0，估 2~3 天）

> 补第 1 条标准；`operation_targets` 从 1/9 推广到 9/9。

1. **frontmatter 元数据全量补齐**（9 个技能）：
   - 既有：`parameters` / `description` / `tags`；
   - 新增（对齐 AutoGen `ToolMeta`）：`risk`（read/write/exec/network）、`path_arg`/`url_arg`、
     `timeout`（秒）、`retry`（瞬态重试次数，默认 0）、`stage`（plan/execute，默认 both）、
     `operation_targets`（各技能的"操作→必有参数键"契约）、`usage`（调用须知）；
2. **`SkillMetadata` 解析扩展**（progressive_loader.py:253 `_parse_frontmatter`）+ 校验：
   bootstrap 时对缺 `risk`/契约的技能打 warning（先软约束，测试断言硬）；
3. **注册中心查询 API**：`get_by_stage(stage)` / `get_by_risk(risk)` / `get_guard_meta(name)`
   （供阶段三 RunGuard 与阶段四白名单消费）；
4. **测试**：`tests/test_agent/test_tool_registry.py`——9/9 元数据完整性、非法 risk 拒绝、
   operation_targets 覆盖断言（1/9 → 9/9 是本阶段的核心度量）。

**验收**：注册中心元数据完整性测试全绿；SKILL.md 双份 schema 漂移问题在 file_operations 上
试点"frontmatter 唯一权威 + prompt 硬编码段引用 frontmatter"（其余技能随后续阶段跟进）。

### 阶段三 · RunGuard 执行前守卫（P0，估 2~3天）

> 搬 AutoGen 三件套核心；与现有 L5 闸门合并为单一检查点。

1. **新建 `app/agent/skills/guard.py`**（蓝本 `security/authorizer.py`）：
   - `ToolGuard.begin(name, params)` 顺序：**注册表白名单**（未注册 → `UNKNOWN_SKILL`）
     → **结构化 schema 校验**（frontmatter `parameters` 走 jsonschema：类型/必填/未知键拒绝
     → `MISSING_PARAM`/`INVALID_TYPE`/`UNKNOWN_KEY`；`operation_targets` 并入此处）
     → **参数级约束**（`safe_path`/`safe_url` 收口自 skill 内散落检查 → `PATH_ESCAPE`）
     → **工具级连续失败熔断**（≥2 次拒第 3 → `CONSECUTIVE_FAILURE`，文案引导"换方式或报告障碍"）
     → **风险门**（`risk∈{write,exec,network}` 且 `APPROVAL_MODE=deny` 拒；一期默认 auto 留钩）；
   - `ToolGuard.finish(name, ok, detail)`：更新失败计数 + **记录审计事件**
     （event/tool/detail/duration_ms → 阶段六 JSONL）；
   - 返回结构化拒绝 JSON（对齐 `_deny` 形态，模型直接可读）。
2. **挂载**：`progressive_loader.execute`（:368）内替换现有 `validate_params_structure` 闸门，
   保持"不通过不进 skill"语义；超时包装（`_execute_with_timeout`）计入 `finish(ok=False, TIMEOUT)`；
3. **配置**：`Settings` 增 `tool_approval_mode: auto|deny`（默认 auto）、`tool_consecutive_fail_limit: 2`；
4. **测试**：`tests/test_agent/test_tool_guard.py`——unknown_skill 拒绝、缺参/类型错/未知键拒绝、
   路径逃逸拒绝、连续 3 次失败熔断、成功重置计数、审批门 deny 模式。

**验收**：传参类错误**在 guard 层被拦并回注结构化 code**，不再穿透到 skill 内手工 if；
黄金门禁全绿。

### 阶段四 · 动态白名单（stage/risk）（P1，估 1~2 天）

> 补第 2 条标准；翻译 AutoGen 角色白名单为阶段白名单。

1. **stage 过滤**：`get_skill_list_str`（progressive_loader.py:505）改按当前 stage 注入——
   规划早期只读集（read 类），执行期全量；stage 由主循环状态推导（todos 已建 → execute）；
2. **risk 过滤（可选开关）**：`tool_deny_risks` 配置（如非 admin 会话禁 network）——一期只留
   配置位与过滤函数，默认空（行为不变，避免误伤）；
3. **prompt 同步**：PLANNING_PROMPT 的硬编码参数段引用 frontmatter（阶段二试点推广），
   避免"注入的工具集"与"参数说明"不一致；
4. **测试**：prompt 工具集随 stage 变化的断言；默认配置下全量注入行为不回归。

**验收**：规划期 prompt 不出现 write/delete 类技能；黄金门禁 + smoke（涉及 prompt 必跑）。

### 阶段五 · 容错闭环补全（P1，估 2 天）

> 补第 3 条标准；处置死代码。

1. **瞬态重试接线**：`guard.finish` 与 loader 之间——`TIMEOUT`/`EXEC_FAILED`（IO 类）按
   registry `retry` 元数据退避重试 1~2 次（仅幂等 read/list 类默认 retry≥1，写类默认 0）；
   **不**复活 `_execute_sequential_with_retry` 死代码（在 loader 层做轻量重试即可）；
2. **死代码处置**（一次 PR 清完，防误导）：`_execute_sequential_with_retry` / `_retry_step` /
   `_execute_parallel_with_deps` / `_observe_execution` / `_handle_partial_failure`（Replanner 唯一
   调用点）/ `_emergency_recovery` / `skills.registry` fallback——**删除或接线二选一，
   本计划统一选删除**（Replanner 若未来要用，从 git 历史找回）；同步修"重复调用 break
   误报达到最大循环次数"的误导文案（main_graph.py:1895-1902）；
3. **测试**：retry 单测（瞬态失败 1 次后成功 / 写类不重试 / 重试耗尽回 `EXEC_FAILED`）；
   删除项的引用 grep 归零。

**验收**：执行层具备"超时→重试→熔断→结构化回注"完整链；黄金门禁全绿。

### 阶段六 · Trace 最小闭环（P1，估 2~3 天）

> 补第 5 条标准；先不引 OTel，靠三件事回答"哪次调用慢/贵/错"。

1. **工具调用打点**：`guard.begin/finish` 记 `duration_ms` + result，写入
   `execution_nodes.meta_data`（复用现有落库点 main_graph.py:1610）+ 结构化审计；
2. **JSONL run 日志**（借鉴 AutoGen `logs/runs/`）：每次 turn 写
   `logs/runs/{session_id}_{ts}.jsonl`——逐事件：llm_call(model/latency/usage)、
   tool_call(name/params_digest/duration/result/error_code)、guard 事件；
   params 存摘要+大小不存全文（防日志爆炸）；
3. **LLM 层打点**：`llm/factory.py` 每次调用 log `model/latency_ms/usage`（当前 llm 包 0 条日志）；
4. **request_id 贯穿**：`execution_nodes.meta_data` 记 request_id，log format 增加 request_id
   （现中间件有但不进日志格式）；
5. **回放补字段**：get-session steps 带回 `duration_ms`/`error_code`/`created_at`
   （agent.py:739-761 组装处）。

**验收**：一次失败调用能从三处交叉定位——DB（execution_nodes）、JSONL（run log）、日志（app.log 含
model/latency）；`tests/test_llm/` 增打点断言。

### 阶段七 · 热插拔 + 可观测依赖收口（P2，估 1~2 天）

1. **热插拔**：`register_executor` 接线（对外 API：`loader.register_executor` 包装为
   `register_skill_executor`）；`_load_module` 记 mtime，变更即失效重载
   （技能改 `skill.py` 不用重启进程）；unregister 提供 `disable_skill(name)`（运行时下架，
   guard 白名单同步拒绝）；
2. **OTel/Langfuse 二选一**：要么按阶段六的 JSONL 之外接入 Langfuse（span 包 llm_call/tool_call），
   要么从 `pyproject.toml` 删除依赖并更正文档——**消除"依赖声明了但零接入"的漂移**（推荐先删，
   Trace 稳定后再评估接入）；
3. **测试**：运行时注册→可调用→注销→`UNKNOWN_SKILL`；mtime 变更后新逻辑生效。

## 3. 里程碑与依赖

```
阶段一 错误协议 ──┐
阶段二 注册中心 ──┼─→ 阶段三 RunGuard（消费一+二的产物）─→ 阶段四 白名单
                  │                                    └→ 阶段五 容错闭环
                  └────────────────────────────────────→ 阶段六 Trace（依赖三的审计点）
                                                        └→ 阶段七 热插拔
```

| 里程碑 | 阶段 | 预估 | 出口条件 |
|---|---|---|---|
| M1 拦得住 | 一+二 | 3~5 天 | 坏参数解析层拦截 + 9/9 注册元数据，传参类错误有结构化 code |
| M2 管得住 | 三+四 | 3~5 天 | RunGuard 单检查点 + stage 白名单生效 |
| M3 错得起 | 五 | 2 天 | 重试/熔断/回注闭环，死代码清零 |
| M4 看得见 | 六+七 | 3~5 天 | 单次调用可回溯（DB+JSONL+日志三角），热插拔可用 |

总计约 **2~3 周**（单人），每阶段独立可交付、可单独回滚（git revert 粒度 = 阶段）。

## 4. 风险与缓解

| 风险 | 缓解 |
|---|---|
| prompt/错误协议改动影响模型行为 | 涉 prompt 必跑 `scripts/smoke/`；correction 字符串匹配兼容期保留一个阶段再移除 |
| 强校验误拦合法调用（未知键=拒可能过严） | 一期 UNKNOWN_KEY 只 warning+放行，跑一周黄金集无误伤再收紧为拒绝 |
| jsonschema 新依赖 | 优先用 stdlib 手写类型/必填检查（frontmatter 结构简单），确需再引 `jsonschema` |
| 死代码删除误伤 | 删除前 grep 全仓引用 + 黄金门禁对照；分独立 commit |
| stage 白名单切断合法规划 | 默认 stage=both，白名单先在测试开启，观察 smoke 后再默认启用 |
| 与前端错误展示契约变化 | error_code 新增字段是增量、不改既有 `error` 文案——前端无需同步改造 |

## 5. 每阶段通用动作清单

1. 先在 `tests/TESTCASES.md` 加用例（新场景建 S 编号小节）→ 测试先红；
2. 实现 → `run_golden.py --fast` → 全量 `run_golden.py` 退出码 0；
3. 涉提示词/图 → 补跑 `scripts/smoke/`；
4. 同步文档：`error-codes.md`（新 code）、`api-spec.yaml`（如有 API 变化）、
   `boundaries.md`（如模块职责变化）、本计划打勾；
5. commit message 中文，前缀 `update:`/`fix:`，独立成 commit。

## 6. 执行记录

| 日期 | 阶段 | 结果 |
|---|---|---|
| 2026-11-16 | 计划定稿 | 待执行 |
| 2026-11-16 | 三个先行快改点二次确认 | 逐条 grep 复核全部属实，登记 §0.5，建议快改 1+2 合并为"传参错误速效包"先行落地 |
| 2026-11-17 | 阶段一（含快改1） | ✅ 完成：`build_plan_interception` 拦截坏计划不进执行；`SkillResult.error_code` 8 码协议 + loader 分类改写；correction 按 code 分支（`_build_correction_hints`）+ 字符串兜底；error-codes.md §7；TESTCASES TC-S7-06~08 |
| 2026-11-17 | 阶段二（含快改2） | ✅ 完成：9/9 SKILL.md 补 risk/path_arg/url_arg/timeout/retry/stage/operation_targets/usage；`*` 通配契约 + validate 接线；非法枚举 raise、缺失 warning；get_by_stage/get_by_risk/get_guard_meta；TESTCASES TC-S14-04~06。附带修复：general_response 降级参数 message→input（原必失败）；prompt 引用 frontmatter 试点归阶段四 |
| 2026-11-17 | 阶段三 | ✅ 完成：新建 `app/agent/skills/guard.py`（ToolGuard 五道关卡：白名单→契约/类型→safe_path·safe_url→连续失败熔断→风险门），挂载 loader.execute 替换原 L5 闸门（不通过不进 skill 语义不变），超时在 `_execute_with_timeout` 补 finish(TIMEOUT)；Settings 增 `tool_approval_mode`/`tool_consecutive_fail_limit`；error_code 增 CONSECUTIVE_FAILURE/RISK_DENIED；TESTCASES TC-S8-07~08。保守策略：未知键一期仅告警、类型检查只拦结构性错误（联合类型已支持） |
| 2026-11-17 | 阶段四 | ✅ 完成：`get_skill_list_str(stage=)` + `filter_skills_by_policy` 纯函数——plan=只读集（risk=read，验收：规划期无 write/exec/network 类）、execute/None=全量 9/9 不回归；Settings 增 `tool_deny_risks`（默认空）；planner 三调用点接线（plan_action/with_feedback→execute，_create_plan_with_llm→plan）；file_operations frontmatter→prompt 参数段试点（`_render_skill_params`，usage 并入"path 不能是 Python 代码"规则）；TESTCASES TC-S14-07~08；门禁 212 passed 全绿 + `scripts/smoke/dbg_flask.py` 真实 LLM 冒烟 5 待办全成功 |
| 2026-11-17 | 阶段五 | ✅ 完成：loader 层瞬态重试（`_invoke` 拆分 + 按 registry retry 元数据线性退避，仅 EXEC_FAILED/未分类失败，耗尽归一 EXEC_FAILED、retry=0 保持 None；结构类拒绝不重试）；死代码删除 421 行——计划 6 项（sequential/retry_step/parallel/observe/partial_failure/emergency）+ registry fallback（main_graph）+ 计划外 2 个零引用孤儿（_build_execution_layers/_generate_step_analysis），全仓引用归零；重复调用 break 的 summary 改报"相同调用重复达到上限"、轮次显示真实预算 _round_budget；TESTCASES TC-S7-09~10 |
