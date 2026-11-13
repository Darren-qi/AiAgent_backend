# 端到端冒烟测试（E2E Smoke）

单元测试（`tests/`）管函数级正确性；本目录管**真实链路**：起服务、发真任务、
走 LLM ReAct、SSE 推流、生产落盘。黄金门禁=`run_golden.py`；改动涉及
图/提示词/技能的，另从本目录取场景脚本冒烟一次。

## 清单

| 脚本 | 场景 | 判据 |
|---|---|---|
| dbg_flask.py | 本地端到端：搭 Flask 博客真任务走 LLM | 5 待办全成功、骨架文件落盘 |
| smoke_anchor.py | 任务目录锚定（开局注入/search 锚定） | 无跨任务目录泄漏、路径正确 |
| rmdir_smoke.py | 空目录清理（move 搬空/删光自动 rmdir） | 空目录消失、非空保留 |
| prod_batch_smoke.py | 生产批量并发创建（files 数组） | 节点日志"批量写入 N/N"、多轮完成 |
| move_e2e.py | 文件归类/移动任务 | 原文件全部迁走、旧目录空则清 |
| lg_stream_e2e.py | SSE 流式接口 | 200、事件流正常终止 |
| smoke_pathfix.py | 读不存在文件的路径修复回归 | 不再裸读根目录/给出定位动作 |
| fullstack_flask_e2e.py | 两阶段真实场景（建Flask博客→Vue3+FastAPI归类，TC-S16-01） | 中间 0 工具失败、根目录只剩前后端两子目录 |

## 怎么跑

- 本地：服务 `.venv/bin/python -m uvicorn app.main:app --port 8000` 起好后，
  `.venv/bin/python scripts/smoke/<脚本>.py`
- 生产：`scp` 到服务器 → `cd /www/wwwroot/aiagent/AiAgent_backend_langgraph && .venv/bin/python3 <脚本>`
- 判定看脚本最后一行 PASS/FAIL 与返回的 RESULT 状态，不做人工目测。

## 测试数据从哪来

- 单测：`tests/conftest.py` fixture（settings/llm/用户）+ 各用例自建带时间戳
  的临时项目目录（`write_test_1794559xxx/`），不依赖外部数据文件。
- 冒烟：脚本内部自建任务与文件（如 Flask 骨架内容），真 LLM 真落盘；
  任务目录在 `tasks/` 下，复测前可手动清理上一次的产物。
