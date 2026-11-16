# 测试用例集（场景清单 · 人话版）

> 给谁看：任何人——看"场景+做什么+预期"就能懂系统被测了什么。
> 给谁用：开发者按场景**手动追加**用例（表格加一行 + 对应自动化函数）。
> 关系：本清单是目录；自动化本体在 `tests/*.py`，门禁 `run_golden.py`，手动冒烟在 `scripts/smoke/`。

状态标记：✅ 自动化（每次门禁自动跑）｜🟡 手动冒烟（scripts/smoke，改动涉及图/提示词/技能时跑）｜⏸ 已隔离（原因见 tests/test_api/conftest.py）｜✍️ 待补自动化（只有人工步骤，欢迎认领）

编号规则：`TC-场景-序号`，新用例接着往下编号，不复用旧号。

---

## S1 创建与文件读写（让 AI 建项目/读写文件，文件必须真实落盘）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S1-01 | 一次创建多文件项目（app.py+HTML+配置）→ 3个文件真实存在且内容逐字正确 | test_file_operations::create_project_structure | ✅ |
| TC-S1-02 | 创建含嵌套目录的项目 → 子目录与文件都建出来 | test_file_operations::nested_directory_creation | ✅ |
| TC-S1-03 | 写单文件 → 落盘、返回 path/project_name/files 齐全 | test_file_operations::write_single_file | ✅ |
| TC-S1-04 | 读文件 → 内容与行号正确 | test_file_operations::read_file | ✅ |
| TC-S1-05 | 列目录 → 返回子项清单 | test_file_operations::list_directory | ✅ |
| TC-S1-06 | 删除文件 → 磁盘上真的消失 | test_file_operations::delete_file | ✅ |
| TC-S1-07 | 会话写入超上限 → 被拒绝 | test_file_operations::session_limit | ✅ |
| TC-S1-08 | 操作名别名（write→write_file 等）→ 同样生效 | test_file_operations::operation_aliases | ✅ |

## S2 批量并发（骨架一次建完，不用逐文件跑多轮）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S2-01 | write 带 files 数组 → 多文件并发落盘、单个失败不影响其余 | test_file_operations::write_batch_files_parallel | ✅ |
| TC-S2-02 | read 带 files 数组 → 多文件并行读回拼接 | test_file_operations::read_batch_files_parallel | ✅ |
| TC-S2-03 | edit 带 edits 数组 → 多处局部替换一次完成（兼容 old/new 与 old_text/new_text） | test_file_operations::test_edit_batch_edits_array | ✅ |

## S3 移动与空目录清理（文件归类任务的核心）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S3-01 | 基本移动 → 源消失、目标出现、内容不变 | test_file_operations::move_file | ✅ |
| TC-S3-02 | 目标已存在（含空目录目标）→ 按 shell mv 语义覆盖 | test_file_operations::move_overwrites_existing_dest / move_over_empty_shell_target | ✅ |
| TC-S3-03 | 目标参数用别名 destination → 同样生效 | test_file_operations::move_destination_alias | ✅ |
| TC-S3-04 | 源=目标同路径 → 幂等不报错 | test_file_operations::move_identical_target_idempotent | ✅ |
| TC-S3-05 | 移动搬空源目录 → 空目录自动删除（非空保留） | test_file_operations::move_cleans_emptied_source_dir | ✅ |
| TC-S3-06 | 删除清空父目录 → 空父目录自动删除（绝不碰任务根） | test_file_operations::delete_cleans_emptied_parent_dir | ✅ |
| TC-S3-07 | 🟡 手动：真实归类任务把散落文件全部移走、原位置不留文件、旧空目录消失 | scripts/smoke/move_e2e.py + rmdir_smoke.py | 🟡 |
| TC-S3-08 | move 带 files 数组 → 多文件一次搬完，键名混用（path/dest、from/to、src/dst）都认 | test_file_operations::test_move_batch_files_array | ✅ |
| TC-S3-09 | 批量移动一项源不存在 → 其余照常、note 记录失败项 | test_file_operations::test_move_batch_partial_failure | ✅ |
| TC-S3-10 | delete 支持 files=[{path}] 与 paths=[...] 批量，一项不存在其余照删 | test_file_operations::test_delete_batch_files_and_paths | ✅ |
| TC-S3-11 | 批量删除后空目录树级联清掉（css→static 整链），任务根与根文件保留 | test_file_operations::test_delete_batch_cascades_empty_dirs | ✅ |
| TC-S3-12 | move 搬空后源目录链级联清掉（app/static 空壳不残留），目标侧保留 | test_file_operations::test_move_cascades_empty_source_chain | ✅ |

## S4 路径锚定与定位（任务只能动自己的目录；找不到文件要给线索）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S4-01 | 裸文件名实际在子目录（如 config.py 在任务根）→ 不误报"缺失" | test_promised_files（4条） | ✅ |
| TC-S4-02 | 真正缺失的文件 → 如实报告缺失 | test_promised_files::truly_missing_still_reported | ✅ |
| TC-S4-03 | 读不存在的同名文件 → 提示去同名子目录找，不裸猜路径 | test_file_operations::read_missing_suggests_same_name_in_subdir | ✅ |
| TC-S4-04 | 🟡 手动：开局注入任务目录锚定，search/list/read 不泄漏其他任务目录 | scripts/smoke/smoke_anchor.py | 🟡 |
| TC-S4-05 | 🟡 手动：读不存在文件的路径修复回归（不再一上来读根目录） | scripts/smoke/smoke_pathfix.py | 🟡 |
| TC-S4-06 | 归类移动后旧路径提及（app/x.py 实在 backend/app/）→ 不误报"不存在" | test_promised_files（slashed/exact 两条） | ✅ |
| TC-S4-07 | 提示词规则不丢：批量移动/先list再访问/失败重试/收尾核对（规则10-12） | test_thought_rules::test_thought_rules_present | ✅ |
| TC-S4-08 | 路径带任务目录名前缀（task/… 或 tasks/task/…）→ 剥前缀在任务目录内解析，不嵌套出 task/task/…、不落 tasks 根 | test_file_operations::test_path_with_task_dir_prefix_resolves_inside_task | ✅ |
| TC-S4-09 | 缺件观察句首=本步状态+缺件问题（"本步操作已成功，但…尚未创建"，2026-11-14 第三次迭代），不写"待办未完成"状态断言，仍带任务目录查找根 | test_promised_files::test_miss_message_puts_task_dir_first | ✅ |
| TC-S7-06 | 写后读回硬跳过：上一动作 write+read 文件⊆刚写列表→不执行并给跳过反馈；读别的文件、edit 后依赖读不受影响（3例） | test_readback_guard | ✅ |
| TC-S7-07 | 重复读硬跳过+退轮：同 turn 同文件第2次 read→跳过并强指令动手（4例，含 turn 重置后首读不误伤、循环层退轮源码断言）；现场=第三轮 5 轮全 read 烧光判失败 | test_duplicate_read_guard | ✅ |

## S5 搜索文件（按内容/文件名找东西）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S5-01 | 打开搜索默认读第一页带行号；offset 续读；小文件一页给完 | test_search_files（default_read/offset/small_file） | ✅ |
| TC-S5-02 | 按内容搜索 → 返回文件+行号+片段 | test_search_files::content_search_returns_file_line_snippet | ✅ |
| TC-S5-03 | count/files_only 输出模式、glob 过滤、文件名模式兜底 | test_search_files（output_mode×2/glob×3/mode_alias/type_alias） | ✅ |
| TC-S5-04 | 路径逃逸（跳出任务目录）→ 拒绝 | test_search_files::path_escape_rejected | ✅ |
| TC-S5-05 | 非法正则 → 报错不崩；缺 pattern → 列目录；零命中 → 明确提示 | test_search_files（invalid_regex/missing_pattern/zero_hit） | ✅ |

## S6 局部编辑（精确替换代码片段）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S6-01 | 原文唯一命中 → 替换成功 | test_file_edit::unique_replace | ✅ |
| TC-S6-02 | 原文找不到 → 报错（不静默） | test_file_edit::not_found_error | ✅ |
| TC-S6-03 | 多处命中不带 replace_all → 拒绝；带了 → 全换 | test_file_edit（multi_hit/replace_all） | ✅ |
| TC-S6-04 | 缺 old_text 参数 → 明确报缺参 | test_file_edit::missing_old_text_param | ✅ |
| TC-S6-05 | 文件不存在/路径不安全 → 拒绝 | test_file_edit（nonexistent/path_safety） | ✅ |
| TC-S6-06 | edit 别名与多行原文精确匹配 | test_file_edit（alias_maps/multiline） | ✅ |

## S7 ReAct 失败反馈与完成判定（工具失败必须回传给模型迭代）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S7-01 | 工具执行失败 → 观察快路径带错误原文+「调整参数重试」，下一轮可修正 | test_observation_parse::observe_tool_failure_fast_path_no_llm | ✅ |
| TC-S7-02 | 完成状态行判定：完成/未完成/部分完成/无状态行 → 结论都不误报 | test_observation_parse（status_line×6） | ✅ |
| TC-S7-03 | 🟡 手动：真实任务里某步失败后，下一轮思考必须引用错误并重试原动作（不许只读绕圈烧轮次） | 生产节点日志核对（2026-11-13 案例：N3015失败→N3017分析→重试） | 🟡 |
| TC-S7-04 | 批量写参数被输出上限截断降级 raw → 抢救 files[] 完整元素照常落盘，截断元素丢弃 | test_file_operations::test_execute_recovers_truncated_raw | ✅ |
| TC-S7-05 | 规则13：新建文件写完不读回确认（只许依赖读/覆盖前读/排障读），减少无谓交替轮次 | test_thought_rules::test_thought_rules_present | ✅ |
| TC-S7-06 | 阶段一·快改1：params_invalid 坏计划在 main_graph 被 `build_plan_interception` 拦截不进执行，返回结构化 error_code（缺目标参数→MISSING_PARAM、非对象→INVALID_TYPE）；正常计划不拦 | test_planner_params_guard::test_params_invalid_intercepted_with_error_code | ✅ |
| TC-S7-07 | 阶段一·error_code 协议：loader 拦截坏参数→SkillResult.error_code=MISSING_PARAM、未注册技能→UNKNOWN_SKILL；skill 内"缺少…参数"文案在 loader 出口统一改写为 code，未分类错误保持 None 走字符串兜底 | test_planner_params_guard::test_error_code_protocol_on_loader_rejections | ✅ |
| TC-S7-08 | 阶段一·correction 按 code 触发：`_build_correction_hints` 优先按 error_code 分支（文案不匹配也命中）、code 优先于字符串、无 code 时字符串兜底不回归、EXEC_FAILED 仅最后兜底 | test_planner_params_guard::test_correction_hints_branch_by_code | ✅ |
| TC-S7-09 | 阶段五·瞬态重试：retry=1 的 search 瞬态失败退避重试 1 次后成功；写类 retry=0 只调 1 次；重试耗尽回 EXEC_FAILED 并计熔断；结构类拒绝（MISSING_PARAM）不重试 | test_transient_retry（4 例） | ✅ |
| TC-S7-10 | 阶段五·死代码清理与文案：`_execute_sequential_with_retry/_retry_step/_execute_parallel_with_deps/_observe_execution/_handle_partial_failure/_emergency_recovery/_build_execution_layers/_generate_step_analysis` 与 main_graph registry fallback 全仓引用归零；重复调用 break 的 summary 报"相同调用重复达到上限"而非误报"达到最大循环次数"（轮次显示真实预算 _round_budget） | grep 归零 + 既有循环用例不回归（门禁） | ✅ |

## S8 安全与守卫（危险请求拦截、正常请求放行、不越界读写）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S8-01 | 危险命令（rm -rf 等）→ 拦截 | test_agent::InputGuard（sanitize等） | ✅ |
| TC-S8-02 | SQL/XSS 文本**不误杀**（任务文本是数据），但注入检测器本身可用 | test_agent（sql_injection/xss_attack） | ✅ |
| TC-S8-03 | API Key 等敏感信息 → 检测+掩码 | test_agent（api_key_detection/mask_sensitive） | ✅ |
| TC-S8-04 | 正常内容 → 放行不拦 | test_agent（normal_content）+ test_components（guard normal） | ✅ |
| TC-S8-05 | 提示注入句式 → 警告不拦截（现契约） | test_components::guard_check_prompt_injection | ✅ |
| TC-S8-06 | 绝对路径逃逸（想写到任务目录之外/文件系统根）→ 拒绝 | test_file_operations::safe_path_check | ✅ |
| TC-S8-07 | 阶段三·RunGuard 五道关卡：未注册→UNKNOWN_SKILL、契约缺参→MISSING_PARAM（保留"参数结构异常"文案）、结构类型错→INVALID_TYPE、未知键一期仅告警放行、路径逃逸（绝对系统路径/..//批量 files[]）与非法 URL 协议→PATH_ESCAPE | test_tool_guard（unknown/missing/type/unknown_key/path/url 6 例） | ✅ |
| TC-S8-08 | 阶段三·熔断与审批门：连续失败≥2 第 3 次 begin 拒（CONSECUTIVE_FAILURE）、成功清零恢复；APPROVAL_MODE=deny 拒 write/exec/network（RISK_DENIED）而 read 放行、默认 auto 不拦；finish 记审计（duration_ms/error_code）供阶段六 JSONL；loader.execute 挂载点透传结构化 code | test_tool_guard（breaker/approval/loader/audit 4 例） | ✅ |

## S9 上下文预算（长对话不爆内存、关键信息不丢）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S9-01 | 128K 预算配置默认值正确、超线才触发压缩 | test_budget_150k（4条） | ✅ |
| TC-S9-02 | 压缩只在轮次结束做；钉住消息/最近观察/待定观察永不被压缩掉 | test_context_manager（compress/pinned/recent_obs/pending 等） | ✅ |
| TC-S9-03 | 压缩前先脱敏；观察超长截断且原文可追溯 | test_context_manager（masking/observation_truncated） | ✅ |
| TC-S9-04 | 按引用卸载/恢复、预取按需加载、去重与过期清理 | test_context_manager（offload/no_preload/prune） | ✅ |

## S10 向量与记忆召回

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S10-01 | 嵌入按序、按64分批、429重试、维度不匹配降级 | test_embedding（embed_sorts/batches/retries/dimension） | ✅ |
| TC-S10-02 | 向量层关闭/缺 key/单条失败 → 不阻塞主流程 | test_embedding（off/missing_key/graceful 等） | ✅ |

## S11 LLM 配置与用量

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S11-01 | 模型配置与请求体构造正确 | test_llm（create_config/create_request） | ✅ |
| TC-S11-02 | 预算检查、用量记录、状态查询 | test_llm（check_budget/record_usage/get_status） | ✅ |
| TC-S11-03 | 路由器与可用模型/策略枚举 | test_llm（create_router/available_models/strategies） | ✅ |
| TC-S11-04 | 阶段六·LLM 打点：factory.chat 每次调用产出 loguru `[LLM]` 行（model/latency_ms/prompt_tokens/completion_tokens/cost，进 app.log）+ JSONL `llm_call` 事件（含 request_id） | test_llm_trace（2 例） | ✅ |

## S12 API 接口

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S12-01 | 健康检查双段路径返回 200 | test_endpoints::health_check | ✅ |
| TC-S12-02 | 登录（username_or_email 字段）成功/凭据错误 | test_endpoints（login×2） | ✅ |
| TC-S12-03 | 任务执行接口带 token 可调、无 token 401 | test_endpoints（agent_execute×2） | ✅ |
| TC-S12-04 | 会话创建、记忆读取接口可用 | test_endpoints（create_conversation/get_memory） | ✅ |
| TC-S12-05 | ⏸ 注册/登录全量/帖子/用户管理 27 条：缺 client fixture 且会写真实库，启用前先建隔离测试库 | test_auth/test_posts/test_users | ⏸ |
| TC-S12-06 | ⏸ 登录成功(有账号)用例：依赖真实库已有 testuser（本地碰巧有=环境假绿） | test_endpoints（TestAuthEndpoint 2条） | ⏸ |
| TC-S12-07 | 阶段六·回放补字段：get-session 过程卡 next_moves 带 duration_ms/error_code、全步骤带 created_at（meta_data 组装链路已落库） | 手动核对接口返回（组装逻辑在 agent.py 闭包内，无单测面） | 🟡 |

## S13 周边服务（通知/存储/社交/用户）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S13-01 | 通知：管理器创建、渠道未配置不发、定时通知参数正确 | test_notification（3条）+ test_email（2条） | ✅ |
| TC-S13-02 | 存储：上传本地/下载/删除/列文件（dict 契约） | test_storage（upload_local/download/delete/list） | ✅ |
| TC-S13-03 | 社交：管理器与飞书/企微渠道创建、无渠道时提示 | test_social（3条）+ test_platforms（2条） | ✅ |
| TC-S13-04 | 用户服务：按标识查用户、创建用户（注入 db） | test_user_service（get_user/create_user） | ✅ |

## S14 子图执行与技能装载

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S14-01 | 子图顺序执行 2 步 → 每步成功、结果齐 | test_components::sequential_execution | ✅ |
| TC-S14-02 | 多结果整合：单结果/多结果都成文 | test_components（integrate×2） | ✅ |
| TC-S14-03 | 技能装载：初始化、元数据、匹配、参数校验 | test_components（bootstrap/metadata/match/validate） | ✅ |
| TC-S14-04 | 阶段二·注册中心 9/9：全部内置技能声明 risk/stage/operation_targets/usage（核心度量 1/9→9/9），timeout/retry 非负 | test_tool_registry::test_nine_nine_metadata_complete | ✅ |
| TC-S14-05 | 阶段二·契约与校验：`*` 通配契约拦无 operation 技能的缺参（http_client 缺 url/search 缺 query/sandbox 无 code·file），file_operations 显式 op 契约不回归；非法 risk/stage 解析层 raise、缺失仅 warning 软约束 | test_tool_registry（star_contract/invalid_risk/missing_warns） | ✅ |
| TC-S14-06 | 阶段二·查询 API：get_by_stage（规划期不含 sandbox/notification）、get_by_risk（exec={sandbox}）、get_guard_meta 切片（未注册 None） | test_tool_registry::test_registry_query_apis | ✅ |
| TC-S14-07 | 阶段四·动态白名单：stage="plan" 只读集注入（验收：规划期 prompt 不出现 file_operations/sandbox/http_client 等 write/exec/network 类）；stage=None/execute 全量 9/9 不回归；tool_deny_risks 黑名单（network,exec）生效且默认空不回归；planner 调用点透传 | test_skill_whitelist（plan_stage/execute_default/deny_risks/pure/planner_pass 5 例） | ✅ |
| TC-S14-08 | 阶段四·prompt 同步试点：file_operations 参数段从 frontmatter 渲染（全量参数键+usage 规则"不能是 Python 代码/≤4文件"+operation 枚举），替代 prompt 硬编码段防双份漂移 | test_skill_whitelist::test_render_skill_params_from_frontmatter | ✅ |
| TC-S14-09 | 阶段六·Trace 最小闭环：run 日志（无 session 禁用、路径 `{session}_{ts}.jsonl`、request_id 贯穿、params 只存摘要不存全文）；guard.finish 返回 duration 事件；loader 出口 duration 挂 SkillResult.metadata + JSONL `tool_call`/`guard_deny` 事件 | test_trace（7 例） | ✅ |
| TC-S14-10 | 阶段七·热插拔：register_skill_executor 运行时注册→立即可调用；disable_skill 下架→guard 白名单拒 UNKNOWN_SKILL、prompt/查询 API 同步剔除、enable 恢复；skill.py mtime 变化→下次加载 importlib.reload（未变不重复 reload）；未知名下架/恢复返回 False | test_hotplug（4 例） | ✅ |
| TC-S14-11 | 阶段七·依赖收口：pyproject 移除零接入的 opentelemetry×3 + langfuse 声明（代码 grep 零引用），overview.md 可观测行同步 | pyproject diff + grep 归零 | ✅ |

## S15 真实 LLM 任务端到端（走完整 ReAct）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S15-01 | 简单任务/带上下文任务执行完成 | test_agent（execute_simple/with_context） | ✅ |
| TC-S15-02 | 搭 Flask 博客完整任务 → 待办全成功、骨架落盘 | test_agent::execute_creates_flask_blog | ✅ |
| TC-S15-03 | 🟡 手动：本地搭博客全流程冒烟（5待办全成功） | scripts/smoke/dbg_flask.py | 🟡 |
| TC-S15-04 | 🟡 手动：生产批量并发创建（节点日志"批量写入 N/N"） | scripts/smoke/prod_batch_smoke.py | 🟡 |
| TC-S15-06 | 🟡 手动：「创建一个fastapi项目」→ 完成+0工具失败+磁盘fastapi证据；行为面断言按**真读**算（节点数−观察"已跳过读取"跳过数）：批量写入≥1、真写后确认读≤1、真读≤6、连续只读轮≤2、单文件真读≤2；跳过次数(jumps)与批量写段数打印报告 | scripts/smoke/fastapi_batch_e2e.py | 🟡 |
| TC-S15-05 | 🟡 手动：SSE 流式接口事件流正常终止 | scripts/smoke/lg_stream_e2e.py | 🟡 |

## S16 用户常用真实场景（两轮连贯手动流程）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S16-01 | 🟡 手动：轮1「创建一个Flask博客项目」→ 中间流程 0 次工具执行失败；轮2「将前端改为vue3框架，后端改为FastAPI框架，并将现有文件归类到前后端目录」→ 正确归类、根目录恰好只剩前后端两个子目录、前端有 .vue、后端有 fastapi 证据 | scripts/smoke/fullstack_flask_e2e.py | 🟡 |
| TC-S16-02 | 🟡 手动：三轮连贯对话，第3轮是修复类任务（给已有项目挂组件/补路由）→ 待办成功收尾，过程区不出现连续重复读导致的"5轮全read达到最大循环次数"空转（生产 2026-11-14 00:12 现场，session_1794585775850；配套自动化=TC-S7-07） | 手动复现：连续3轮发消息，第3轮让系统改已有文件，核对无重复读空转 | 🟡 |
| TC-S16-03 | 🟡 手动：任务失败收尾后发「继续」→ 期望恢复上轮未完成待办继续执行且全程0次工具执行失败；现场（生产 2026-11-14 01:39，session_1794585775850）：失败收尾 clear_state 清掉未完成事项→生成字面量待办"继续"→edit 用 files[] 批量形态连续2次报"缺少 path 参数"（01:39:12/01:39:32）→0文件改动却标✅完成。**已修（2026-11-14）**：①失败收尾不再 clear_state，改 note_failure+failed_error 落库，下一轮 cap_restore 由 judge_continue 判续/弃（继续→复位失败待办续跑；新任务→丢弃；截断续跑原行为不变）②edit 支持 files[] 批量且兼容 old_string/new_string 键 ③失败/验收拒绝/异常三处收尾统一记断点 ④先落库再发终态事件（e2e 首跑实测：前端收到 complete/error 即断开→本任务被 cancel→后置 await 被打断→断点没清+任务误标"任务被取消"；已按 agent.py「先落库再通知前端」原则把4处终态事件重排为先持久化再 emit） | tests/test_agent/test_resume_checkpoint.py（断点落库取回/续/弃/截断回归/直通 共10例）+ test_file_operations::test_edit_batch_files_array（原 xfail 已转正）+ scripts/smoke/resume_e2e.py（真实两轮 e2e：建任务→播种失败断点→发「继续」→断言 resumed 事件/edit files[] 执行/断点消费/任务 completed/0 缺参） | ✅ 2026-11-14 本地 e2e PASS |
| TC-S16-04 | ✅ 单测：过程区连续报"工具执行失败: 缺少 path 参数"（生产 2026-11-14 23:00:59-23:06:56，session_1794668306070 共5次，第5次换 files[] 才成功）。**根因取证**：planning 原文（execution_nodes id4672/4788/4792/4796）显示模型把大 .vue 文件内容内联进一条参数 JSON，生成结构崩坏——参数 keys 变成代码碎片（name/component/props/…）、只剩尾部 operation/task_path、没有 path；解析器 _extract_json 把它当合法 dict 放行（planner.py:919-996）→执行必报缺 path。**深层原因**：SKILL.md 正文传参须知（含"单次批量≤4文件/≤6000字，超出会被输出上限截断成残缺JSON"的同款警告，file_operations/SKILL.md:98）从未进 prompt——平时只发名称+一句话+tags（progressive_loader.py:488-499），出错 JIT 也只给 frontmatter schema（无 files/edits、无批量规模）。**已修（2026-11-14 A+B 一起）**：A=frontmatter parameters 补 files/edits/paths/old_text/new_text/replace_all+新增 operation_targets 契约与 usage 调用须知，出错 JIT 注入"全量 schema+调用须知"（渐进第三级），三处规划 prompt 补"单次≤4文件/≤6000字"警告；B=_parse_planning_response 标 params_invalid 不放行 + progressive_loader.execute 执行前按 operation_targets 契约拦截（缺目标参数→结构化错误走 correction 回注 schema/须知），未声明契约的 skill 不拦 | tests/test_agent/test_planner_params_guard.py 6 例（坏参数标记+reason、正常/list/批量/注入键不误伤、loader.execute 拦截、hint 含批量参数+调用须知+≤4文件）+ tests/ 全量 188 passed | ✅ 2026-11-14 本地 188 passed |

## S17 界面过程区展示（折叠行表头/摘要不重复、失败才露根因）

| 编号 | 用例：做什么 → 预期 | 自动化 | 状态 |
|---|---|---|---|
| TC-S17-01 | 折叠动作行表头"读取文件"+摘要只带对象（posts.py），不同格再写一遍"读取文件"；思考/计划/完成行摘要留空 | 前端无测试框架 → build 后人工目视 StepItem 折叠行 | 🟡 |

---

## 怎么手动追加用例（开发者）

1. 在对应场景表里加一行：`TC-场景-下一个序号 | 人话描述（做什么→预期） | 自动化函数名或"待补" | ✅/🟡/✍️`
2. 自动化：在对应 `tests/test_*.py` 写同名测试函数（命名对上表里的函数名）
3. 跑 `.venv/bin/python run_golden.py` 全绿才算进集；手动/冒烟用例在"状态"列标 🟡 并写清跑法
4. 发现线上 bug：先补一条能复现它的用例（红）→ 再修（绿）——用例永久留在集里
