# 当前迭代（Sprint）

> 快照时间：2026-11-16｜分支：`master`｜基线提交：`7729a0b update: 优化多轮对话的能力`
> 本文按仓库当前**未提交改动**（`git status`/`git diff`）整理；完成一项勾一项，
> 合并后在文末"迭代记录"追加一行。规则见 [../conventions/testing.md](../conventions/testing.md)。

## 迭代主题

**用户级 LLM 计费 + 失败断点续跑 + 规划参数守卫**——三条主线并行，全部围绕
"多轮长任务的可靠性与成本归属"。

## 任务清单

### A. 用户级 DeepSeek API Key（计费到人）

| 项 | 内容 |
|---|---|
| 目标 | 用户在「设置 → 通用设置」填自己的 DeepSeek key → 该用户所有 LG 后端 LLM 调用走自己的 key 计费；未填/查询失败回落系统 key，装载失败绝不阻塞任务 |
| 状态 | 🔄 进行中（代码基本就绪，待门禁全绿后提交） |
| 实现 | `app/agent/llm/user_api_key.py`（contextvar 按 asyncio task 隔离，并发不串）；每 turn 开始在 `main_graph.execute` set，`factory.chat` DeepSeek 选型时读取注入；provider 按 key 复用专属 client |
| 存储 | `users.deepseek_api_key`，迁移 `alembic/versions/009_add_user_deepseek_api_key.py` |
| API | `GET/PUT /api/v1/users/profile/llm-key`（掩码返回 `sk-***3456`，空串=清除） |
| 测试 | `tests/test_agent/test_user_api_key.py` ✅ |

### B. 失败断点续跑（发「继续」恢复上轮未完成待办）

| 项 | 内容 |
|---|---|
| 目标 | 任务失败收尾不再清状态；下一轮由 `judge_continue` 判"继续/丢弃"——继续则复位失败待办续跑，新任务则丢弃断点 |
| 状态 | 🔄 进行中（e2e 已 PASS，随本批提交） |
| 实现 | 失败收尾改 `note_failure` + `failed_error` 落库；验收拒绝/异常三处收尾统一记断点；`edit` 支持 `files[]` 批量并兼容 `old_string/new_string` 键；**4 处终态事件重排为先落库再 emit** |
| 依据 | 生产现场 session_1794585775850（2026-11-14 01:39）：clear_state 导致字面量待办"继续"、edit 连续缺参 |
| 测试 | `tests/test_agent/test_resume_checkpoint.py`（10 例）✅、`scripts/smoke/resume_e2e.py` 本地 e2e PASS、TESTCASES `TC-S16-03` |

### C. Planner 参数守卫（坏参数不放行）

| 项 | 内容 |
|---|---|
| 目标 | 模型把大文件内容内联进参数 JSON 导致结构崩坏 → 执行必报"缺少 path"；现在解析层标记 + loader 层拦截 |
| 状态 | 🔄 进行中（188 passed，随本批提交） |
| 实现 | A：SKILL.md frontmatter 补 `files/edits/paths/old_text/new_text/replace_all` + `operation_targets` 契约 + 调用须知，出错 JIT 注入"全量 schema+须知"（渐进第三级），三处规划 prompt 补"单次≤4文件/≤6000字"；B：`_parse_planning_response` 标 `params_invalid` 不放行 + `progressive_loader.execute` 按契约拦截回注 correction |
| 依据 | 生产 session_1794668306070（2026-11-14 23:00-23:06，5 次缺 path） |
| 测试 | `tests/test_agent/test_planner_params_guard.py`（6 例）✅、TESTCASES `TC-S16-04` |

### D. 用量追踪与会话计费

| 项 | 内容 |
|---|---|
| 目标 | LLM 真实 usage（token/费用）追踪并按会话聚合，支撑预算与计费展示 |
| 状态 | 🔄 进行中 |
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

## 待办 / 下一步

- [ ] 本批改动跑全量门禁 `.venv/bin/python run_golden.py`，退出码 0 后提交 A–E；
- [ ] Dockerfile 改用 `pyproject.toml` 安装（`pip install .`），清理 Flask 残留
      `requirements.txt`（见 [../architecture/overview.md](../architecture/overview.md) §7）；
- [ ] endpoints 中 ~20 处裸 `HTTPException` 分批迁移 `AppException` 子类；
- [ ] `app/api/v1/router.py` 死代码清理（或恢复为唯一挂载方式，二选一收口）；
- [ ] AutoGen 后端（:8001）ContextManager 二期评估（`CONTEXT_MANAGER_PLAN.md` §8）。

## 迭代记录

| 日期 | 内容 |
|---|---|
| 2026-11-16 | 建立 docs 七件套；整理未提交改动为 A–E 五条主线 |
| 2026-11-14 | 断点续跑、planner 参数守卫、usage 计费三线开工（生产现场驱动） |
| 2026-11-13 | 黄金测试集建立（23 failed + 27 errors → 修复/隔离至全绿） |
