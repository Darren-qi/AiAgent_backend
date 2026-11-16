# 测试规范（LangGraph 后端）

> 规则源自 `tests/GOLDEN.md`（2026-11-13 用户制定）与 `tests/TESTCASES.md`；
> 本文是操作手册，冲突时以这两个文件原文为准。
> 关联：编码规范 [README.md](README.md)｜当前迭代 [../plans/current-sprint.md](../plans/current-sprint.md)。

## 1. 三层测试体系

| 层 | 位置 | 跑法 | 何时跑 |
|---|---|---|---|
| 黄金单测集 | `tests/**/*.py` | `.venv/bin/python run_golden.py` | **每次改动全量跑** |
| 快验（跳过真实 LLM） | 同上 | `.venv/bin/python run_golden.py --fast` | 提交前 |
| 手动/链路冒烟 | `scripts/smoke/`（见其 SMOKE.md） | 逐脚本执行 | 改动涉及**图/提示词/技能**时 |

- 退出码 0 = 无清单外新失败；退出码 1 = 出现新失败，**必须处理后才能交付**；
- `--fast` 跳过 `LLM_TESTS` 名单（依赖真实 LLM、慢且偶发波动），名单在 `run_golden.py`；
- pytest 配置：`testpaths = ["tests"]`、`asyncio_mode = "auto"`（异步测试直接 `async def`）。

## 2. 黄金测试集铁律

1. **新问题先补用例再修**：复现该问题的测试先进黄金集（先红），修复后转绿，
   用例永久保留——不许"修完就删测试"；
2. **每次改动跑全量**：不允许只跑"我觉得相关的"子集；
3. **豁免唯一入口**：`tests/golden_allowlist.txt`，每条必须写原因：

   ```
   tests/xxx/test_yyy.py::TestClass::test_name   # 失败原因（必写）
   ```

4. **清单只能变短**：运行器发现清单内用例转绿会提示移除；禁止为过门禁随手加新豁免；
5. **隔离比跳过安全**：`tests/test_api/conftest.py` 模块级隔离了
   test_auth/test_posts/test_users（缺 client fixture 且会写真实数据库）；
   启用前必须先建隔离测试库 + 补 fixture。

## 3. 用例清单（TESTCASES.md）管理

- `tests/TESTCASES.md` 是**人话版场景目录**：看"场景 + 做什么 + 预期"即可懂被测行为；
- 自动化本体在 `tests/*.py`，本清单只做索引——**新增用例两边同步**（表格一行 + 测试函数）；
- 编号规则：`TC-场景-序号`（如 `TC-S16-03`），**接着往下编号，不复用旧号**；
- 状态标记：

  | 标记 | 含义 |
  |---|---|
  | ✅ | 自动化，每次门禁自动跑 |
  | 🟡 | 手动冒烟（`scripts/smoke/`），改图/提示词/技能时跑 |
  | ⏸ | 已隔离（原因见 `tests/test_api/conftest.py`） |
  | ✍️ | 待补自动化，只有人工步骤 |

- 复杂修复把**现场证据**（生产时间、session_id、根因、修法）写进用例行，
  这是本仓库的惯例（参考 TC-S16-03/04 的写法）。

## 4. 测试目录组织

```
tests/
├── conftest.py            # 全局 fixtures（mock settings/user/agent context、token 校准隔离）
├── TESTCASES.md           # 场景清单（目录）
├── GOLDEN.md              # 黄金集规则（本规范的源头）
├── golden_allowlist.txt   # 唯一豁免清单
├── test_agent/            # 最大套件：图执行、文件操作、守卫、checkpoint、planner 参数…
├── test_context/          # ContextManager/预算/embedding（22 条）
├── test_api/              # auth/users/posts（自带 conftest，部分隔离）
├── test_llm/              # LLM 调用与 usage 追踪
├── test_services/         # UserService 等
└── test_storage/ test_social/ test_notification/
```

- 按**被测模块**分目录，与 `app/` 结构大致对齐；
- 测试文件名 `test_<模块>.py`；共享 fixture 放 `conftest.py`，域内私有放同目录；
- 真实 LLM/外部服务必须 mock 或走 replay，单测不许烧钱（真实链路归 smoke）。

## 5. 写测试的约定

```python
# 示例骨架（与现有 test_agent 风格一致）
async def test_edit_batch_files_array():
    """edit 支持 files[] 批量且兼容 old_string/new_string 键。"""
    ...  # 断言行为，不断言实现细节
```

1. 中文 docstring 说明**测什么场景**，与 TESTCASES 行对应；
2. 断言对外行为（落盘结果、返回结构、事件语义），避免耦合内部变量名；
3. 涉及文件操作的测试用临时任务目录，绝不触碰真实 `tasks/` 根；
4. 参数化优先（同场景多输入用 `@pytest.mark.parametrize`）；
5. 已知坑回归必须有专测（如"先落库再推事件"、断点恢复、路径锚定）。

## 6. 冒烟脚本（scripts/smoke/）

- 真实链路 E2E：锚定、批量创建、移动归类、空目录、SSE、路径修复、断点续跑
  （`resume_e2e.py`）等 7+ 场景，见 `scripts/smoke/SMOKE.md`；
- 触发条件：改动涉及 **图 / 提示词 / 技能** 时，单测之外必须补跑；
- 冒烟产出可留证据（日志/截图）附到 TESTCASES 对应 🟡 行。

## 7. 新增测试的完整动作清单

1. 在 `tests/TESTCASES.md` 对应场景表加一行（新场景先建 `S编号` 小节）；
2. 在对应 `tests/test_*/` 目录写自动化函数；
3. `.venv/bin/python run_golden.py --fast` 快验；
4. 提交前全量 `run_golden.py`，退出码必须为 0；
5. 涉及图/提示词/技能 → 额外跑 `scripts/smoke/` 相关脚本。
