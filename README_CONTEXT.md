# ContextManager 使用说明（LangGraph 后端）

> 可插拔上下文管理器：**按需加载、step 级 masking、turn 级压缩、按引用恢复**。
> 方案与验收对照见项目根 `CONTEXT_MANAGER_PLAN.md`；本文是规则↔配置↔扩展点速查。
> 范围：一期仅 `AiAgent_backend_langgraph`（:8000）；AutoGen 后端二期（方案 §8）。

## 1. 术语映射（规范 → 代码）

| 规范术语 | 落点 | 说明 |
|---|---|---|
| step | `main_graph.py` `_execute_todo_with_loop()` 内一次 think→plan→execute→observe | 计数器 `self._ctx_step`（turn 内单调递增） |
| turn | `AgentGraph.execute()` 一次调用（一个用户请求） | ContextManager 在此新建、在 `finally` 里 `on_turn_end` |
| 上下文构建点 | hook 1：组 `thought_context` 之后、`planner.think()` 之前 | 每 step 重建（BuildResult） |
| Observation 后 | hook 2：`last_error` 算出之后 | `on_observation()` 登记+预算+step 级 masking |
| turn 后 | hook 3：`execute()` 的 `finally` | `on_turn_end()` 压缩/折叠——全量淘汰唯一入口 |
| 外部存储 | `store.py`：`MemoryStore`（默认兜底） / `PgSaverStore` | 卸载原文，按 `external_ref` 恢复 |

## 2. 三钩子接入位置（main_graph.py）

```python
execute() 入口          → ContextManager(cfg, embed_fn) + on_session_start(task)   # 失败降级 None
hook1  think 之前        → on_step_start(step, query=state.task) → 追加 BuildResult.prompt
hook2  last_error 之后   → on_observation(obs_id, content[:4000], tool, ...)
hook3  execute() finally → on_turn_end() → 日志 saved/offloaded/folded → mgr=None
```

三条铁律：
1. 每个钩子都包在 `try/except` 里——**上下文管理失败只降级、绝不阻塞任务执行**；
2. step 级只允许 masking/索引化，**全量压缩只发生在 hook3**；
3. 任何被移除的内容必须 `external_ref` 可恢复（或 pinned 固定保护）。

## 3. 配置（app/core/config.py，全部可配无硬编码）

| Settings 字段 | 默认 | 对应策略 |
|---|---|---|
| `context_max_tokens` | 60000 | 上下文 token 预算（按主模型窗口配） |
| `context_compress_trigger_ratio` | 0.7 | 超 70% 触发压缩 |
| `context_compress_target_ratio` | 0.5 | 压回 50% |
| `context_protect_recent_steps` | 2 | 最近 N step 的观察不淘汰 |
| `context_turn_compress_min_steps` | 10 | turn 内 step 超此值 → 轨迹折叠 |
| `context_external_store` | memory | `memory` \| `pgsaver` |
| `context_recall_enabled` / `context_recall_mode` | True / `trigger+vector` | 召回开关与分层（`off`/`trigger_only`/`trigger+vector`） |
| `context_similarity_threshold` | 0.5 | 向量召回余弦阈值 |

读取方式：`get_settings().build_context_config()` → `ContextConfig`（`app/agent/context/config.py`）。

## 4. 扩展点（三个插拔位）

```python
ContextManager(
    cfg=...,                       # 策略
    embed_fn=ZhipuEmbedder().embed_one,   # 向量层：智谱 embedding-3；无 ZHIPU_API_KEY 时传 None → 跳过向量召回
    store=PgSaverStore(...),       # 外部存储：默认 MemoryStore 进程内兜底
    summarizer=fn,                 # turn 级 LLM 摘要：注入后 _summarize_item 用之，否则确定性一行摘要
)
```
- **LLM 摘要**：`summarizer`（协议 `(text) -> str`），默认不用（成本控制）；
- **向量检索**：`embed_fn` + `RecallConfig(mode=...)`，回忆侧只做内存余弦，零网络调用；
  query embedding 只在"存在索引态候选"时才计算（`recall.py` 先筛候选）；
- **外部存储**：实现 `ExternalStore.put/get` 协议后 `register_store("name", cls)`。

## 5. 可解释性

- `BuildResult`：`used_tokens / omitted[] / masked[] / recall / reasons`——每 step 构建结果可查；
- `CompressResult`：`reason(budget|turn_end|long_loop|manual) / saved / offloaded / folded / decisions`；
- `ContextManager.decisions_log()`：全量决策文本（项/动作/原因）。
- 运行日志：`[CtxMgr] turn 开始`、`[CtxMgr] step=N used=… omitted=… masked=…`、`[CtxMgr] turn_end …`。

## 6. 测试

```bash
.venv/bin/python -m pytest tests/test_context/ -q     # 22 条（规范 §6 的 9 个必测用例全覆盖）
```
覆盖：常驻项恒在 / 最近 N step 保护 / 未消费观察绝不动 / 超限先 masking / 白名单只摘要 /
压缩只在 turn 后 / 70%→50% / 按 ref restore / 不预加载（JIT）+ embedding 客户端 mock 测试。

## 7. 已知边界（一期不做）

- AutoGen 后端（:8001）：需包装 `OpenAIChatCompletionClient.create()`，二期单独排期；
- 跨会话知识库：`experience` 表无 embedding 列，二期加 pgvector 迁移；
- embedding 为同步 httpx（钩子内每批一次 HTTP），async 化二期；
- `calibrate(actual, estimated)` 钩子已留：拿到 API 真实 prompt_tokens 后校准 tiktoken 估算。
