# 当前迭代（Sprint）

> 快照时间：2026-11-17｜分支：`master`｜基线提交：`1c8625c feat: 工具层 Harness 阶段七——热插拔与可观测依赖收口`
> 本文按仓库改动整理；完成一项勾一项，
> 合并后在文末"迭代记录"追加一行。规则见 [../conventions/testing.md](../conventions/testing.md)。
> 2026-11-17 更新：A–E 已全部提交（`36477e1`），工作区干净；新增 G 条目（工具层 Harness 七阶段）。
> 2026-11-18 更新：新增 H 条目（阶段八：写操作幂等 + 断点可靠性），工作区 17 改 + 8 新文件待提交。

## 迭代主题

**用户级 LLM 计费 + 失败断点续跑 + 规划参数守卫**——三条主线并行，全部围绕
"多轮长任务的可靠性与成本归属"。

## 任务清单

### A. 用户级 DeepSeek API Key（计费到人）

| 项 | 内容 |
|---|---|
| 目标 | 用户在「设置 → 通用设置」填自己的 DeepSeek key → 该用户所有 LG 后端 LLM 调用走自己的 key 计费；未填/查询失败回落系统 key，装载失败绝不阻塞任务 |
| 状态 | ✅ 已完成（2026-11-17 随 `36477e1` 提交，门禁全绿） |
| 实现 | `app/agent/llm/user_api_key.py`（contextvar 按 asyncio task 隔离，并发不串）；每 turn 开始在 `main_graph.execute` set，`factory.chat` DeepSeek 选型时读取注入；provider 按 key 复用专属 client |
| 存储 | `users.deepseek_api_key`，迁移 `alembic/versions/009_add_user_deepseek_api_key.py` |
| API | `GET/PUT /api/v1/users/profile/llm-key`（掩码返回 `sk-***3456`，空串=清除） |
| 测试 | `tests/test_agent/test_user_api_key.py` ✅ |

### B. 失败断点续跑（发「继续」恢复上轮未完成待办）

| 项 | 内容 |
|---|---|
| 目标 | 任务失败收尾不再清状态；下一轮由 `judge_continue` 判"继续/丢弃"——继续则复位失败待办续跑，新任务则丢弃断点 |
| 状态 | ✅ 已完成（2026-11-17 随 `36477e1` 提交，e2e PASS + 门禁全绿） |
| 实现 | 失败收尾改 `note_failure` + `failed_error` 落库；验收拒绝/异常三处收尾统一记断点；`edit` 支持 `files[]` 批量并兼容 `old_string/new_string` 键；**4 处终态事件重排为先落库再 emit** |
| 依据 | 生产现场 session_1794585775850（2026-11-14 01:39）：clear_state 导致字面量待办"继续"、edit 连续缺参 |
| 测试 | `tests/test_agent/test_resume_checkpoint.py`（10 例）✅、`scripts/smoke/resume_e2e.py` 本地 e2e PASS、TESTCASES `TC-S16-03` |

### C. Planner 参数守卫（坏参数不放行）

| 项 | 内容 |
|---|---|
| 目标 | 模型把大文件内容内联进参数 JSON 导致结构崩坏 → 执行必报"缺少 path"；现在解析层标记 + loader 层拦截 |
| 状态 | ✅ 已完成（2026-11-17 随 `36477e1` 提交；后续 Harness 阶段一~三在其上扩展 error_code 协议/RunGuard，见 G） |
| 实现 | A：SKILL.md frontmatter 补 `files/edits/paths/old_text/new_text/replace_all` + `operation_targets` 契约 + 调用须知，出错 JIT 注入"全量 schema+须知"（渐进第三级），三处规划 prompt 补"单次≤4文件/≤6000字"；B：`_parse_planning_response` 标 `params_invalid` 不放行 + `progressive_loader.execute` 按契约拦截回注 correction |
| 依据 | 生产 session_1794668306070（2026-11-14 23:00-23:06，5 次缺 path） |
| 测试 | `tests/test_agent/test_planner_params_guard.py`（6 例）✅、TESTCASES `TC-S16-04` |

### D. 用量追踪与会话计费

| 项 | 内容 |
|---|---|
| 目标 | LLM 真实 usage（token/费用）追踪并按会话聚合，支撑预算与计费展示 |
| 状态 | ✅ 已完成（2026-11-17 随 `36477e1` 提交，门禁全绿） |
| 实现 | `app/agent/llm/factory.py` usage 校准扩展、`router.py`/`types.py` 配套字段、`roundcap_judge.py` 轮次裁判增强、`budget.py` 预算联动 |
| 测试 | `tests/test_llm/test_usage_tracking.py`、`tests/test_agent/test_session_billing.py` ✅ |

### E. 缺件观察句第三轮迭代

| 项 | 内容 |
|---|---|
| 目标 | 缺件观察句首 = 本步状态 + 缺件问题（"本步操作已成功，但…尚未创建"），不再写"待办未完成"状态断言，仍带任务目录查找根 |
| 状态 | ✅ 已完成（含在本批） |
| 依据 | TESTCASES `TC-S4-09` 措辞更新（2026-11-14 第三次迭代） |
| 测试 | `tests/test_agent/test_promised_files.py` ✅ |

### F. 文档体系（本次新增）

| 项 | 内容 |
|---|---|
| 目标 | `docs/` 七件套：架构总览、模块边界、编码规范、测试规范、API 规范、错误码、本清单 |
| 状态 | ✅ 已完成（2026-11-16） |
| 交付 | `docs/architecture/{overview,boundaries}.md`、`docs/conventions/{README,testing}.md`、`docs/reference/{api-spec.yaml,error-codes.md}`、`docs/plans/current-sprint.md` |

### G. 工具层 Harness 升级（2026-11-17，独立计划）

| 项 | 内容 |
|---|---|
| 目标 | 工具层从"文本协议 + 手工 if"升级为"注册中心 + 守卫检查点 + 结构化错误 + 可观测"的 Harness，结构性消灭传参类错误 |
| 计划 | [tool-harness-upgrade.md](tool-harness-upgrade.md)（3 快改 + 7 阶段，执行记录已全部勾完） |
| 状态 | ✅ 已完成（阶段一~七全部交付，六条 Harness 标准全达成） |
| 交付 | 阶段一错误协议+拦截前移 `2eedc48`｜阶段二注册中心 9/9 `2eedc48`｜阶段三 RunGuard `2eedc48`｜阶段四动态白名单+prompt 同步 `53a54dc`｜阶段五瞬态重试+死代码清理 `0f9a165`｜阶段六 Trace 三角 `33f7ee4`｜阶段七热插拔+依赖收口 `1c8625c` |
| 测试 | 黄金门禁 229 passed 全绿；新增 test_tool_registry/test_tool_guard/test_skill_whitelist/test_transient_retry/test_trace/test_llm_trace/test_hotplug 共 38 例（另 test_planner_params_guard 扩 3 例）；真实 LLM 冒烟 dbg_flask PASS |

## 待办 / 下一步

- [x] 本批改动跑全量门禁 `.venv/bin/python run_golden.py`，退出码 0 后提交 A–E（✅ 2026-11-17：`36477e1` 提交，后续门禁持续全绿至 229 passed）；
- [x] Dockerfile 改用 `pyproject.toml` 安装（`pip install .`），清理 Flask 残留
      `requirements.txt`（✅ 2026-11-17：双 Dockerfile 改 `pip install .`、删
      requirements.txt、compose context `./backend`→`.`、新增 .dockerignore，
      `pip install --dry-run .` 验证通过；镜像构建待有 docker 环境复核）；
- [x] endpoints 中 ~20 处裸 `HTTPException` 分批迁移 `AppException` 子类（✅ 2026-11-17：20 处全迁 deps5/agent14/auth1，`raise HTTPException` grep 归零，401 保留 WWW-Authenticate 头，前端兜底增 `.data.error`，error-codes §1.4/§3/§4 同步）；
- [ ] `app/api/v1/router.py` 死代码清理（或恢复为唯一挂载方式，二选一收口）；
- [ ] AutoGen 后端（:8001）ContextManager 二期评估（`CONTEXT_MANAGER_PLAN.md` §8）。

## H. 工具层 Harness 阶段八：写操作幂等 + 断点可靠性（2026-11-18）

### P0 写操作幂等：崩溃后重试不重复副作用
- **意图日志表** `app/models/action_journal.py` + `alembic/versions/010_add_action_journal.py`（op_key 唯一、status=running/done/failed/ambiguous、params/result 快照、两个索引）。
  ⚠️ 本地库没有 `alembic_version`（表由 `init_db` 的 create_all 建），**不要在这库上跑 `alembic upgrade head`**（会从 001 全量重放）；`upgrade head --sql` 也会在 003 离线取连接处崩，单步验证用 `upgrade 009:010 --sql`。
- **裁决树** `app/agent/execution_journal.py` → `EXECUTE / REPLAY / AMBIGUOUS_SIDE_EFFECT`：
  - 语义五级解析：`op_semantics[op]` → `*` → `retry>=1` → `risk=read` → **兜底 once（不可重放）**
  - `idempotent`：不写库，零开销
  - `once`：新 op 写 intent；`running` → AMBIGUOUS（崩溃/超时残留，宁可少做不可重做）；`done` 在 120s 新鲜窗口内重放、过期放行（避免老 done 误杀合法重跑）；**已判 ambiguous 一次后模型仍原样重发 = 知情决定 → 放行**（否则一次性操作永久卡死）
  - `conditional`：永远先做世界状态核验（技能 `verify_replay`）：True=重放结果（无快照也给 success）、False=放行重跑、None=退化按状态判定
  - DB I/O 全 fail-open；`_purge_stale()` 每进程每小时清 7 天前数据；`purge_session()` 供任务收尾清理
- **接线** `progressive_loader.execute`：摘 `_op_ctx` → 解析语义 → `open_journal` → replay/ambiguous 直接返回 → 正常执行后 `close_journal`；**CancelledError 不收尾**（残留 running 正是崩溃证据）。
- **file_operations**：SKILL.md 声明 read/list/write=idempotent、create=once、edit/move/delete=conditional；`verify_replay`（存在性核验，先过 `_is_safe_path`）；`_atomic_write_text()`（同目录 tmp + fsync + `os.replace`）接入 write/edit/create 三处，杜绝半截文件。
- **错误码闭环**：`TOOL_ERROR_CODES` 加 `AMBIGUOUS_SIDE_EFFECT`，guard 熔断跳过该码，planner 修正提示"先核验再决定，禁止原样重发"，`docs/reference/error-codes.md` §7 登记。

### P1 断点可靠性：save 失败不再静默
- **version 乐观锁**：`pgsaver.save_working(expected_version=…)` — UPDATE 带 `WHERE version=旧行`，rowcount=0 再走"只复活软删行"的 upsert；`ExecutionStateManager._version` 跟踪基线，冲突时采纳库里新基线重试一次，仍失败才计数上报。旧状态行无 version 键按 0 兼容。
- **save 失败上报**：`on_checkpoint_error` → `AgentGraph._report_checkpoint_error` → SSE `checkpoint_error`（每轮最多 3 条；回调异常吞掉；前端未订阅=无副作用）。
- **执行前 pending_action（写前快照）**：派发前 `begin_pending_action` + `save_state()` 落库，`finally` 清内存标记 → 进程在 action 中途被杀，库里留着"卡在哪一步"；恢复时 `prepare_resume` 写一条「【断点】上次中断时正在执行: X」并清标记。只存 action + params sha256 前 8 位，不存参数原文。
- **去掉重复 save**：main_graph 每次 action 后的第二次 `save_state()` 删除（同一轮白写一遍库）。
- **TaskManager 终态落库** `app/agent/task_persistence.py`：stopped/completed/failed 同步 UPDATE `tasks`（fire-and-forget、completed 不被覆盖、fail-open），`agent._finalize_db_task` 转调同一实现；**create 不落库**（行创建时本就是 running，重复写没有信息量，少一次连接占用）。启动 `init_db()` → `sweep_orphan_tasks()` 把超 2 小时的 running/pending 标 failed。

### 验证
- 新增 4 个测试文件：`test_action_journal`(30) / `test_checkpoint_version`(14) / `test_atomic_write`(7) / `test_task_persistence`(8)；全量 **289 passed, 29 skipped**（基线 229 passed）。
- 真实 PG 探针（跑完即清理）：CAS 首插/正常递增/冲突返回 0/旧行无 version 兼容 全过；journal running→done→fresh replay→ambiguous→verify True/False→purge_session 全链路全过。
- ⚠️ 墙钟时间：全量 286s，其中 `test_billed_accumulates_across_turns` 与 `test_agent.py` 三个 graph 用例占大头；同一条代码在不同次运行里 20s~150s 都出现过（user CPU 仅 2s，纯外部等待），**无证据表明与本批改动有因果关系**，已排除 `create` 落库这一项后仍复现。

## 迭代记录

| 日期 | 内容 |
|---|---|
| 2026-11-18 | **阶段八**：写操作幂等（action_journal WAL + 语义白名单 + 原子写）+ 断点可靠性（version 乐观锁 / save 失败上报 / pending_action 写前快照 / TaskManager 终态落库）；289 passed |
| 2026-11-17 | A–E 随 `36477e1` 提交；工具层 Harness 七阶段全部交付（`2eedc48`→`1c8625c` 共 5 个 feat commit），门禁 229 passed 全绿 |
| 2026-11-16 | 建立 docs 七件套；整理未提交改动为 A–E 五条主线 |
| 2026-11-14 | 断点续跑、planner 参数守卫、usage 计费三线开工（生产现场驱动） |
| 2026-11-13 | 黄金测试集建立（23 failed + 27 errors → 修复/隔离至全绿） |
