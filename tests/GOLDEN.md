# 黄金测试集（Golden Test Set）

> **人话版场景用例清单：`tests/TESTCASES.md`（先看这个——15 个场景、68 条用例，
> 含手动/隔离标记；开发者按场景往里追加）。** 规则见下。

> 2026-11-13 用户制定：专门维护一个测试集；发现新问题在原有基础上追加
> 测试用例，后续继续基于黄金测试集迭代；每次改动跑全部测试，避免改了
> 一个问题、其他地方又出问题。

## 怎么跑

```bash
.venv/bin/python run_golden.py          # 全量（标准门禁）
.venv/bin/python run_golden.py --fast   # 跳过真实 LLM 测试（提交前快验）
```

改动涉及**图/提示词/技能**时，除单测外另跑 `scripts/smoke/`（见其 SMOKE.md，
7 个真实链路场景：锚定/批量创建/移动归类/空目录/SSE/路径修复）。

- 退出码 0 = 无新增失败（允许清单内的历史豁免）
- 退出码 1 = 出现清单外的新失败，必须处理后才能交付/同步

## 铁律

1. **新问题先补用例再修**：复现该问题的测试先进黄金集（先红），
   修复后转绿（先红后绿），用例永久保留。
2. **每次改动跑全量**：不允许只跑"我觉得相关的"子集。
3. **豁免唯一入口**：`tests/golden_allowlist.txt`，每条必须写原因；
   禁止为了过门禁把新失败随手加进清单。
4. **清单只能变短**：运行器发现清单内用例转绿会提示移除。
5. **隔离比跳过安全**：`tests/test_api/conftest.py` 模块级隔离了
   test_auth/test_posts/test_users（缺 client fixture 且会写真实数据库）；
   启用它们前必须先建隔离测试库 + 补 fixture。

## 清单格式（tests/golden_allowlist.txt）

```
tests/xxx/test_yyy.py::TestClass::test_name   # 失败原因（必写）
```

## 基线历史

- 2026-11-13 建集前：23 failed + 27 errors（陈旧断言/契约漂移/缺基础设施）
- 2026-11-13 建集：全部修复或隔离（详见 git diff），目标 failed=0
