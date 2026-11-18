# 阶段八改动清单（写操作幂等 + 断点可靠性）— 待复审

> 用途：给更高级模型**按条复审**用。每条含「改了什么 / 为什么 / 风险点 / 验证证据」。
> 生成时间：2026-11-18。分支 `master`（工作区未提交：17 改 + 8 新文件）。
> 复审时请对照最新代码逐条核验，不要只信本文档的自述。

---

## 0. 背景与目标

后端 `AiAgent_backend_langgraph` 是手写执行循环（全库无 langgraph import），断点状态存 PG `working_memory`。
本轮解决两个问题：

1. **P0 写操作幂等**：进程崩溃/中断后重试，不得重复执行一次性副作用（重复扣款、重复发通知、重复执行命令）。
2. **P1 断点可靠性**：并发/断点场景的快照一致性（乐观锁）、save 失败静默丢弃、崩溃时不知道"断在哪个动作"、`tasks` 表状态永不更新。

---

## 1. 改动文件总览

| 文件 | 类型 | 摘要 |
|---|---|---|
| `app/models/action_journal.py` | 新 | 写操作意图日志表模型（WAL） |
| `alembic/versions/010_add_action_journal.py` | 新 | 建表迁移（含 4 索引 + op_key 唯一） |
| `app/agent/execution_journal.py` | 新 | 裁决树：EXECUTE / REPLAY / AMBIGUOUS + 落库脱敏 |
| `app/agent/task_persistence.py` | 新 | TaskManager 终态状态落库通道 |
| `app/agent/memory/pgsaver.py` | 改 | `save_working` 乐观锁 CAS（+expected_version） |
| `app/agent/execution_state.py` | 改 | version 跟踪/重试、save 失败上报、pending_action |
| `app/agent/graphs/main_graph.py` | 改 | 写前快照、删重复 save、checkpoint_error 通道 |
| `app/agent/skills/core/progressive_loader.py` | 改 | journal 接入（语义解析 + 裁决 + 收尾） |
| `app/agent/skills/file_operations/skill.py` | 改 | `verify_replay` 世界状态核验 + `_atomic_write_text` |
| `app/agent/skills/file_operations/SKILL.md` | 改 | `op_semantics` 语义声明（幂等/条件/一次性） |
| `app/agent/skills/guard.py` | 改 | AMBIGUOUS_SIDE_EFFECT 不计熔断 |
| `app/agent/graphs/nodes/planner.py` | 改 | 一次性操作歧义时的修正提示 |
| `app/agent/skills/core/base_skill.py` | 改 | 注册 `AMBIGUOUS_SIDE_EFFECT` 错误码 |
| `app/db/session.py` | 改 | ActionJournal 注册、`sweep_orphan_tasks` 启动兜底 |
| `app/agent/task_executor.py` | 改 | TaskManager 三个终态转移点同步落库 |
| `app/api/v1/endpoints/agent.py` | 改 | `_finalize_db_task` 转调 task_persistence（消除双实现） |
| `app/models/__init__.py` | 改 | 导出 ActionJournal |
| `docs/reference/error-codes.md` | 改 | 新增 §7 一次性副作用歧义 |
| `docs/plans/current-sprint.md` | 改 | 新增 H 节（阶段八机制 + 环境坑） |
| `tests/test_agent/test_action_journal.py` | 新 | 33 用例（裁决树 + 语义契约 + 脱敏） |
| `tests/test_agent/test_checkpoint_version.py` | 新 | 14 用例（乐观锁/上报/pending_action） |
| `tests/test_agent/test_atomic_write.py` | 新 | 7 用例（原子写） |
| `tests/test_agent/test_task_persistence.py` | 新 | 8 用例（终态落库守卫） |
| `tests/test_agent/test_resume_checkpoint.py` | 改 | `_FakeSaver` 补 `expected_version` 签名 |
| `tests/test_agent/test_readback_guard.py` / `test_duplicate_read_guard.py` | 改 | fake Graph 补 `_task_id`、fake execute 摘 `_op_ctx` |

---

## 2. P0：写操作幂等（按条目）

### P0-1 意图日志表 `action_journal`
- **改了什么**：新表（session_id/task_id/todo_id/action/op_key/semantics/params/status/result/error/时间戳），`op_key` 唯一索引，`status` ∈ running/done/failed/ambiguous。无外键（崩溃日志必须永远写得进去）。
- **为什么**：执行前落一行 intent，进程崩溃时残留 `running`，下一轮重入据此判断"上次是否已生效"。
- **风险点**：① 迁移文件**没真跑过 upgrade**（本地库无 `alembic_version` 表，跑 `upgrade head` 会从 001 全量重放——见 §5-1）；② `params` 是长期留存的 JSON，敏感信息风险见 P0-7。
- **验证**：`/tmp/journal_probe.py` 用真实 PG `ActionJournal.__table__.create` 建表并跑通全链路后清理（建表即由 ORM 生成，与迁移内容一致性由 010 的离线 SQL 对照确认）。

### P0-2 裁决树 `execution_journal.py`
- **改了什么**：
  - 语义解析五级优先级：`op_semantics[op]` → `*` → `retry>=1` → `risk=read` → **兜底 once（不可重放）**。
  - `idempotent`：不写库（零开销，read/list/write 这类高频操作零成本）。
  - `once`：新 op 写 intent（running）；残留 running → `AMBIGUOUS`；残留 done → 120 秒新鲜窗口内 `REPLAY`（复用已存结果），过期放行；残留 failed → 放行；**已判 ambiguous 一次后的知情重试 → 放行**（否则一次性操作永远卡死，见 §5-6）。
  - `conditional`：**永远先世界状态核验**（`verify_replay`）：True=REPLAY（无快照也判成功）、False=放行重跑、None=退化状态判定。
  - 所有 DB I/O fail-open（挂了日志绝不挡执行）。
- **风险点**：fail-open 意味着 **DB 不可用期间无幂等保护**（降级为旧行为）——这是有意取舍，但要明确。
- **验证**：`test_action_journal.py`（33 用例）+ `/tmp/journal_probe.py` 真实 PG 全链路（running→done→fresh replay→crash ambiguous→verify True/False→purge_session）。

### P0-3 `progressive_loader.execute` 接入
- **改了什么**：摘掉 `_op_ctx`（不进技能参数）→ 解析语义 → `open_journal` 裁决 → REPLAY/AMBIGUOUS 直接返回（**副作用不执行**）→ 执行 → `close_journal` 写结果；`CancelledError` **不收尾**（残留 running = 崩溃证据）。
- **风险点**：① `params.pop("_op_ctx")` 会改调用方 dict（main_graph 的 `step["params"]`）——目前无影响，但调用方若复用该 dict 需注意；② verification 结果为 None 时 `close_journal` 判 ambiguous（保守）；③ 核验函数抛错 → 退化状态判定，不挡执行。
- **验证**：`test_action_journal.py::TestLoaderAmbiguousPath`（崩溃残留 → AMBIGUOUS_SIDE_EFFECT 且文件没被删）。

### P0-4 `file_operations` 语义声明 + 世界状态核验 + 原子写
- **改了什么**：
  - `SKILL.md` frontmatter `op_semantics`：read/list/write=idempotent、create=once、edit/move/delete=conditional。
  - `verify_replay(operation, **params)`：edit/delete/create/move 存在性核验（走既有 `_is_safe_path` / `_resolve_safe`）；未知 op 返回 None。
  - `_atomic_write_text`：同目录临时文件 + fsync + `os.replace`，接 write/edit/create 三处，杜绝"崩溃后半个文件"。
- **风险点**：① `_collect_paths` 用多个参数别名（path/dest/destination/source/target）做机械收集——与技能自身的参数契约一致，但新增了契约面；② `os.umask(0)` 的极短竞态窗口（见 §5-3）。
- **验证**：`test_atomic_write.py`（中文/多行/覆盖/建父目录/无残留/权限）+ `test_action_journal` 的 verify 三分支。

### P0-5 错误码闭环
- **改了什么**：新增 `AMBIGUOUS_SIDE_EFFECT`；`guard` 熔断不计该码；planner 修正提示（"先核验再决定，禁止原样重发"）；`docs/reference/error-codes.md` §7。
- **风险点**：防护本质是"提示词约束 + 保留状态"，**模型仍可能不核验就重发**（见 §5-6）。
- **验证**：单测覆盖 guard 跳过、planner 提示注入。

### P0-6 运维兜底
- **改了什么**：`purge_session()`（任务成功收尾清该会话 journal）、`_purge_stale()`（每进程每小时清 7 天前）、`init_db()` 调 `sweep_orphan_tasks()`（running/pending 超 2 小时标 failed）。
- **风险点**：`_purge_stale` 是每进程节流（多 worker 各清一次，无害）；`sweep_orphan_tasks` 的 2 小时阈值意味着**并发第二实例**会被误标 failed（单实例部署下无此问题）。
- **验证**：`purge_session` 在 `/tmp/journal_probe.py` 实跑验证；`sweep_orphan_tasks` 有单测（"启动兜底"）。

### P0-7 落库参数脱敏（2026-11-18 复查新增）
- **改了什么**：`_redact_params()` —— 敏感键（token/secret/password/api_key/authorization/cookie/credential/private_key/...）值 → `***REDACTED***`；字符串 >1500 截断；列表 >100 截断；嵌套深度 ≤6。**op_key 仍用原始参数计算**（重放匹配不受影响）。
- **为什么**：意图日志 `params` 长期留存且运维可查，而 `http_client.headers`（Authorization）、`notification` 收件人、`sandbox.code` 都可能带密钥/PII——本轮安全复查发现的唯一实质漏洞，已修。
- **验证**：`test_action_journal.py::TestParamsRedaction`（3 用例：掩码、截断、op_key 不受影响）。

---

## 3. P1：断点可靠性（按条目）

### P1-1 快照 version 乐观锁
- **改了什么**：`save_working(..., expected_version=N)` → UPDATE 带 `WHERE version = 旧行`（旧行无 version 按 0 匹配，用 `ver_col.is_(None)`）→ rowcount=0 时走"只复活软删行"的 upsert（`ON CONFLICT ... WHERE deleted_at IS NOT NULL`）→ 仍冲突返回 0。`ExecutionStateManager` 跟踪 `_version`，冲突时**采纳库内新 base 重试一次**，仍败才计 `save_failures` 并上报。
- **为什么**：并行/断点续跑下两份状态互相覆盖（丢失待办进度）。
- **风险点**：① CAS 路径**返回值语义变了**（返回 1/rowcount，不再是 insert id）——现有调用方只判真假（`context/store.py:59`、`short_term.py:88` 不传 expected_version 走原路径），未来若有人用返回 id 会踩坑（§5-2）；② `expected_version=0` 用 `is_(None)` 匹配"version 键缺失"，显式 `version: 0` 的行会判冲突——现有代码不会写 0（`next_version ≥ 1`）。
- **验证**：`/tmp/cas_probe.py` 真实 PG 四断言（首插/递增/冲突返回 0/旧行兼容）+ `test_checkpoint_version.py`（14 用例含冲突自愈）。

### P1-2 save 失败上报
- **改了什么**：`on_checkpoint_error` 回调（`AgentGraph._report_checkpoint_error`）→ SSE `checkpoint_error` 事件（每轮最多 3 条），回调异常吞掉不影响执行。
- **风险点**：前端目前无订阅者（no-op，无需改前端）；失败仍有兜底 note，不静默丢。
- **验证**：`test_checkpoint_version` 的上报用例 + 回调异常用例。

### P1-3 执行前 pending_action 写前快照
- **改了什么**：`_execute_single_step` 派发前 `begin_pending_action(action, params)` + `save_state()`（写前落库）→ `finally` 清内存标记（由 1864 行 per-action save 落库清掉）；恢复时 `prepare_resume` 写一条「【断点】上次中断时正在执行: X」进 scratchpad 并清标记。**只存 action + params 的 sha256 前 8 位**（不存参数原文，见 §5-8）。
- **为什么**：崩溃时只知道"断在 todo N"，不知道断在哪个动作、要不要复核副作用。
- **风险点**：每次 action 多一次 `save_state`（写前）——DB 往返 +1，量级毫秒级；`pending_action.params_digest` 包含 `_op_ctx`（因为注入在前），同参数不同 todo 会得到不同摘要（无害，仅指纹）。
- **验证**：`test_checkpoint_version.py::TestPendingAction`（3 用例：派发那一刻库里带 pending_action / finally 清理 / prepare_resume 注入提示）。

### P1-4 删重复 save
- **改了什么**：删掉 `_execute_single_step` 里每 action 的**重复** `save_state()`（保留 1864 行的那一次，注释已更新）。
- **验证**：`test_resume_checkpoint.py` 全绿（断点恢复语义未变）。

### P1-5 TaskManager 终态落库
- **改了什么**：新模块 `task_persistence.py`：`persist_task_status`（只 UPDATE 不 INSERT、completed 不被覆盖、fail-open）+ `schedule_task_status`（有事件循环 fire-and-forget，引用防 GC）。`TaskManager` 的 **stopped/completed/failed** 三个终态转移点调用；`create` **不落库**（行创建时本就是 running，重复写纯冗余）。`agent._finalize_db_task` 转调同一实现（规则只留一份）。
- **为什么**：TaskManager 状态只在内存，进程一退 `tasks.status` 永远停在 running。
- **风险点**：① fire-and-forget 在进程退出时可能丢写——靠 `sweep_orphan_tasks`（2h）兜底（§5-7）；② 无事件循环（同步上下文）直接跳过落库（日志 + 兜底）。
- **验证**：`test_task_persistence.py`（8 用例：守卫在 SQL、终态落库、create 不落库、无循环跳过、异常不抛）。

### P1-6 日志小修（复查发现）
- `sweep_orphan_tasks` 原先 `logger.warning(f"...%d...", n)` —— f-string 里 `%d` 不会被格式化（输出字面 `%d`，`n` 丢失）。已改为 `{n}` 插值。

---

## 4. 关键设计决策与被否决的备选

1. **语义默认"不可重放"（once）**：安全优先——未声明语义的技能按一次性处理，宁可误报 AMBIGUOUS 也不重复副作用。备选"默认幂等"被否。
2. **ambiguous 残留放行"知情重试"**：模型收到 `AMBIGUOUS_SIDE_EFFECT` 并被要求先核验；若它决定再发一次，视为知情决定，放行（否则一次性操作永久卡死）。备选"永远拒绝"被否（死锁）。
3. **conditional 永远先世界状态核验**：文件存在性等核验成本低、误判代价小；核验 True 直接复用已存结果（连快照都没有也判成功）。备选"只看 journal 状态"被否（file 这类资源可能被外部改动）。
4. **journal DB I/O 全 fail-open**：可用性 > 强一致。降级为旧行为（无幂等保护），有日志。
5. **op_key 用原始参数、落库副本脱敏**：重放匹配必须精确（参数变一点就该是新操作），留存可查性必须去敏——两者用两份数据各司其职。
6. **pending_action 只存摘要**：精确重放旧参数是危险动作（模型可能照抄过期参数），摘要只做"断在哪"的线索。
7. **create 不落库**：行创建即 running，重复写无信息量（该结论来自冗余性分析，不是性能修复——性能对照实验无定论，见 §5-4）。
8. **单测试 / 双写都不做**：每次 action 多一次写前快照是断点语义所需；不做异步批量（丢写风险）。

---

## 5. 已知风险 / 未验证点（诚实清单，请重点复审）

1. **alembic 010 没真跑 upgrade**：本地库无 `alembic_version`，`upgrade head` 会从 001 全量重放（003 在离线模式取连接会崩）。只验证了 `upgrade 009:010 --sql` 离线 SQL 与 ORM `create_all` 建表。**有 alembic 的环境（生产/新库）首次上线前需要确认迁移可跑**。
2. **`save_working` 返回值语义变化**（CAS 路径返回 1/rowcount 而非 insert id）：现有调用方只判真假，未受影响；属隐性契约变化。
3. **`_atomic_write_text` 的 umask 竞态**：`os.umask(0)` 短暂生效期间，同进程其它线程并发建文件可能拿到 0666 权限。uvicorn 单进程 asyncio 下风险极小，未修，属已知取舍。
4. **性能疑云未定论**：全量 286s vs 基线 113s；`test_billed_accumulates_across_turns` 单测 20~150s 波动（user CPU 仅 2s，纯外部等待），同一代码状态多次运行差异巨大。**"create 落库导致 51s→148s"的归因已被后续对照推翻**（移除后仍复现 111s），文档与代码注释已改为不宣称因果。根因未定位，**不要把它当已修复项复审**。
5. **journal fail-open**：DB 挂 → 无幂等保护（按设计降级）。
6. **ambiguity 防护本质是软约束**：planner 提示要求"先核验再决定"，但模型若不核验就重发，仍会重复副作用。这是提示词 + 状态保留的组合防护，不是硬闸门。
7. **fire-and-forget 落库可能丢写**（进程退出瞬间），靠 `sweep_orphan_tasks`（2h）兜底；同步上下文（无事件循环）直接跳过。
8. **pending_action 不存参数原文**：恢复时只有动作名 + 摘要，无法精确重放参数（有意为之）。
9. **未做**：未提交、未同步服务器、未重启服务；前端无需改动；`tests/TESTCASES.md` 未补本阶段用例（RiffCode 故障处置流程只覆盖示例入库）。
10. **多实例部署**：`sweep_orphan_tasks` 的 2h 阈值会把并发实例正在跑的任务误标 failed；`_purge_stale` 每进程各自触发（无害）。单实例部署无此问题。

## 6. 验证证据汇总

| 证据 | 结果 | 位置 |
|---|---|---|
| 全量 pytest（改动后，含复查修复） | **292 passed, 29 skipped**（基线 229 passed） | `/tmp/pytest_final3.txt`（3m41s，EXIT=0） |
| 新增用例 | action_journal 33 / checkpoint_version 14 / atomic_write 7 / task_persistence 8 | `tests/test_agent/` |
| CAS 真实 PG 探针 | 首插/递增/冲突返回 0/旧行兼容 全过（跑完清理） | `/tmp/cas_probe.py` |
| journal 真实 PG 全链路 | running→done→fresh replay→crash ambiguous→verify True/False→purge 全过 | `/tmp/journal_probe.py` |
| alembic 010 离线 SQL | `upgrade 009:010 --sql` 生成正确 | 手工核对 |
| 安全复查 | 无 SQL 注入（全 ORM 参数化）；无新增路径穿越面（核验走 `_is_safe_path`）；探针/日志不打印凭据；params 落库脱敏已补 | 本轮回查 |

## 7. 建议复审重点（给更高级模型）

1. `execution_journal.open_journal` 的裁决树分支完备性（尤其 ambiguous 放行、done 新鲜窗口、conditional verify=None 退化）。
2. `pgsaver.save_working` 的 CAS 语义（`expected_version=0` 的 `is_(None)` 匹配、软删复活路径、返回值语义）。
3. `progressive_loader.execute` 的收尾路径：REPLAY/AMBIGUOUS 早退、`CancelledError` 不收尾、异常时 close_journal 是否遗漏（残留 running 的误伤面）。
4. P1-3 的写前快照时序：崩溃点落在"save 之后、派发之前"与"派发之后、finally 之前"分别恢复成什么状态。
5. §5 的 10 条风险逐条判定：哪些可接受、哪些必须在上线前修。
