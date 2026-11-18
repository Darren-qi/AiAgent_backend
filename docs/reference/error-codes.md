# 错误码参考（LangGraph 后端）

> 定义位置：`app/core/exceptions.py`｜全局处理器：`app/main.py:134-173`
> 关联：架构总览 [../architecture/overview.md](../architecture/overview.md) §5｜API 规范 [api-spec.yaml](api-spec.yaml)

## 1. 响应格式

### 1.1 业务异常（AppException）

```json
{
  "error": "文章 (ID: 42) 不存在",
  "status_code": 404,
  "error_code": "NOT_FOUND",
  "extra": { "resource": "文章", "resource_id": 42 }
}
```

- `error`：人类可读中文信息（可直接展示给用户）；
- `error_code`：**前端分支判断的稳定标识**（新增必须登记本表）；
- `extra`：结构化附加数据，可选。

### 1.2 请求体校验失败（RequestValidationError → 422）

```json
{
  "error": "请求参数验证失败",
  "error_code": "VALIDATION_ERROR",
  "details": [
    { "field": "body.username", "message": "String should have at least 3 characters", "type": "string_too_short" }
  ]
}
```

### 1.3 未捕获异常（Exception 兜底 → 500）

| 环境 | 响应 |
|---|---|
| 生产 | `{"error": "服务器内部错误", "error_code": "INTERNAL_ERROR"}`（脱敏） |
| 开发 | 追加 `"detail": str(exc)` 与 `"type"` 类型名 |

### 1.4 存量裸 HTTPException（已清零，2026-11-17）

FastAPI 默认形态 `{"detail": "..."}` 曾来自 endpoints/deps 层 20 处直接
`raise HTTPException(...)`（deps 5 / agent 14 / auth 1）——**已全部迁移**为
AppException 子类（§2 分类表），响应回统一信封 `{error, status_code, error_code}`；
401 的 `WWW-Authenticate` 头经 `headers` 参数保留。前端错误读取兜底同步增加
`.data.error`（FilePreview / agent index）。**新代码禁止引入裸 HTTPException**。

## 2. 错误码总表（AppException 体系）

### 2.1 认证类（401）

| error_code | 类 | HTTP | 默认文案 | 抛出场景 |
|---|---|---|---|---|
| `UNAUTHORIZED` | `UnauthorizedException` | 401 | 认证失败，请重新登录 | 通用未认证 |
| `INVALID_CREDENTIALS` | `InvalidCredentialsException` | 401 | 用户名或密码错误 | 登录失败（`services/auth.py`） |
| `TOKEN_EXPIRED` | `TokenExpiredException` | 401 | 令牌已过期，请重新登录 | access token 过期 |
| `INVALID_TOKEN` | `InvalidTokenException` | 401 | 无效的令牌 | 令牌损坏/签名错/刷新令牌无效 |

### 2.2 权限类（403）

| error_code | 类 | HTTP | 默认文案 | 抛出场景 |
|---|---|---|---|---|
| `FORBIDDEN` | `ForbiddenException` | 403 | 您没有权限执行此操作 | 通用禁止 |
| `INSUFFICIENT_PERMISSIONS` | `InsufficientPermissionsException` | 403 | 权限不足 | 角色不足（如非管理员） |
| `USER_INACTIVE` | `UserInactiveException` | 403 | 用户账户未激活 | 账号未激活 |
| `USER_BANNED` | `UserBannedException` | 403 | 用户账户已被禁用 | 账号被封 |

### 2.3 资源类（404 / 409）

| error_code | 类 | HTTP | 默认文案 | 抛出场景 |
|---|---|---|---|---|
| `NOT_FOUND` | `NotFoundException` | 404 | {resource}不存在 / {resource} (ID: x) 不存在 | 资源缺失（`services/post.py` 等）；`extra` 带 resource/resource_id |
| `ALREADY_EXISTS` | `AlreadyExistsException` | 409 | {resource}已存在 | 冲突；`extra` 带 identifier |
| `EMAIL_ALREADY_EXISTS` | `EmailAlreadyExistsException` | 409 | 邮箱已存在 | 注册邮箱重复 |
| `USERNAME_ALREADY_EXISTS` | `UsernameAlreadyExistsException` | 409 | 用户名已存在 | 注册用户名重复 |

### 2.4 请求类（400 / 422）

| error_code | 类 | HTTP | 默认文案 | 抛出场景 |
|---|---|---|---|---|
| `BAD_REQUEST` | `BadRequestException` | 400 | 请求参数错误 | 业务前置条件不满足（如"用户不存在"、"不能删除自己"、无权编辑文章） |
| `VALIDATION_ERROR` | `ValidationException` | 422 | 数据验证失败 | 手动校验失败；`extra.validation_errors` 携带明细（与 §1.2 全局 handler 同名，注意来源区分） |

### 2.5 服务类（500 / 503）

| error_code | 类 | HTTP | 默认文案 | 抛出场景 |
|---|---|---|---|---|
| `INTERNAL_ERROR` | `InternalServerException` | 500 | 服务器内部错误 | 未预期错误（通常走兜底 handler） |
| `SERVICE_UNAVAILABLE` | `ServiceUnavailableException` | 503 | 服务暂时不可用 | 依赖不可用；`extra.retry_after` 可带建议重试秒数（如会话创建失败 503） |

## 3. 依赖注入层 401/403（deps.py，已迁 AppException，2026-11-17）

`app/api/deps.py` 抛 AppException 子类（401 带 `WWW-Authenticate: Bearer` 头，
`error_code` 进统一信封）：

| HTTP | error_code | 文案 | 条件 |
|---|---|---|---|
| 401 | `UNAUTHORIZED` | 请先登录 / 用户身份无法映射，请重新登录 | 未携带 Authorization / token 有效但用户查不到 |
| 401 | `INVALID_TOKEN` | 无效的访问令牌 / 令牌中缺少用户标识 | token 校验失败/过期/`sub` 缺失 |
| 403 | `INSUFFICIENT_PERMISSIONS` | 需要管理员权限 | 已登录但 `role != "admin"` |

> `get_current_user_optional` 对上述异常返回 None（可选认证语义不变，
> AppException 继承 HTTPException 故原 `except HTTPException` 仍兜住）。

## 4. HTTPException 典型文案（已迁移至 AppException，留档对照）

| HTTP | detail | 位置示例 |
|---|---|---|
| 400 | 标题不能为空 / 标题过长 | `endpoints/posts.py` |
| 401 | 请先登录 | `endpoints/agent.py`（rename 强制登录） |
| 403 | 无权操作该会话 | `endpoints/agent.py` |
| 404 | 会话不存在 | `endpoints/agent.py` |
| 400 | 文件路径非法 / 是目录 | `endpoints/agent.py`（read-file 防穿越） |
| 503 | 会话创建失败，请稍后重试 | `endpoints/agent.py` |
| 422 | （Pydantic 默认） | 全局 handler 统一转 §1.2 格式 |

> 迁移规则：改为对应 AppException 子类并复用/新增 error_code，同时更新本表。

## 5. Agent SSE 流错误（不走 HTTP 状态码）

`POST /api/v1/agent/execute/stream` 在流建立后，错误以事件表达
（事件全集见 [api-spec.yaml](api-spec.yaml) 的 SSE 章节）：

| 事件 | data | 触发 | 任务落库状态 |
|---|---|---|---|
| `error` | `{"message": "..."}` | 输入守卫拒绝（流最前端）、执行异常、图内重复调用中断 `{"content","todo_id"}` | `failed` |
| `stopped` | `{"message": "任务已被终止" / "任务已被用户中断"}` | 用户 abort、前端断连取消 | `failed`（"任务被取消"） |
| `complete` | 结果 dict（`success:false` 也算终态） | 执行结束 | `success=false` → `failed`；否则 `completed` |

非流式 `POST /execute/` 不用 SSE：守卫拒绝直接返回
`AgentExecuteResponse{success:false, error}`（HTTP 仍 200），最终回答经
`output_guard.check` 掩码后返回。

## 6. 新增错误码检查单

1. 在 `app/core/exceptions.py` 增加/复用子类，填 `error_code` 常量语义（UPPER_SNAKE）；
2. 在本文 §2 对应分类表登记一行；
3. `app/api/` 抛出点用该子类，不裸写 HTTPException；
4. 若前端需要分支处理，同步前端 `src/types/` 的错误码常量；
5. 补/改测试（黄金集铁律：先红后绿）。

## 7. 工具层错误码（SkillResult.error_code，2026-11-16 阶段一）

Agent 循环内工具层的结构化错误协议，与 §2 AppException 体系**并行不交叉**：
AppException 管 HTTP 响应，本节管循环内 correction 分支（不走 HTTP 状态码）。

- 定义：`app/agent/skills/core/base_skill.py`（`TOOL_ERROR_CODES` + `SkillResult.error_code`）
- 分类器：`progressive_loader.classify_params_problem`（结构问题）、`classify_tool_error`（文案改写）
- 透传链：loader/执行层 → `execution_result["error_code"]` → main_graph `last_error_code`
  → planner `_build_correction_hints` 按 code 给修正策略（字符串匹配兼容期兜底）
- 拦截链（快改1）：planner `params_invalid` → `main_graph.build_plan_interception`
  → 不进执行直接走 correction

| error_code | 触发 | 产出点 |
|---|---|---|
| `MISSING_PARAM` | 缺必填/目标参数（含"缺少…参数"文案统一改写） | loader 契约拦截、skill 缺参报错 |
| `INVALID_TYPE` | params 非 JSON 对象 | `validate_params_structure` |
| `UNKNOWN_KEY` | 未知参数键（一期预留，未启用拒绝） | 阶段三 RunGuard |
| `TRUNCATED_JSON` | 输出截断致 JSON 残缺 | 预留（阶段三识别） |
| `UNKNOWN_SKILL` | 技能未注册 | loader `_load_module` 失败 |
| `PATH_ESCAPE` | 路径逃逸出任务目录 | 预留（阶段三收口 safe_path） |
| `TIMEOUT` | 步骤执行超时 | `main_graph._execute_with_timeout` |
| `EXEC_FAILED` | 执行期异常 | loader/main_graph 兜底 exception |
| `CONSECUTIVE_FAILURE` | 工具级连续失败熔断（≥`tool_consecutive_fail_limit` 拒下一次） | `guard.ToolGuard.begin`（阶段三） |
| `RISK_DENIED` | 风险门拒绝（`tool_approval_mode=deny` 且 risk∈write/exec/network） | `guard.ToolGuard.begin`（阶段三） |
| `AMBIGUOUS_SIDE_EFFECT` | 崩溃残留的写操作无法确认是否生效，交回模型先核验再决定是否重做 | `execution_journal.open_journal`（阶段八，2026-11-18） |

**本节专用检查单**：新增 code → `TOOL_ERROR_CODES` + 上表 + `planner._build_correction_hints`
分支（如需专属修正策略）+ 测试断言。前端无需同步（增量字段，`error` 文案不变）。
