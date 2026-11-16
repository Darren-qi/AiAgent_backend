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

### 1.4 存量裸 HTTPException（无 error_code）

FastAPI 默认形态 `{"detail": "..."}`，主要来自 endpoints 层 ~20 处直接
`raise HTTPException(...)`。**新代码禁止引入**，逐步迁移到 AppException 子类。
典型 detail 文案见 §4。

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

## 3. 依赖注入层 401/403（deps.py，无 error_code）

`app/api/deps.py` 抛的是裸 `HTTPException`（带 `WWW-Authenticate: Bearer`）：

| HTTP | detail 文案 | 条件 |
|---|---|---|
| 401 | 请先登录 | 未携带 Authorization |
| 401 | 无效的访问令牌 | token 校验失败/过期/`sub` 缺失 |
| 401 | 用户身份无法映射，请重新登录 | token 有效但用户查不到 |
| 403 | （CurrentAdminUser 默认） | 已登录但 `role != "admin"` |

## 4. 存量 HTTPException 典型文案（逐步迁移）

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
