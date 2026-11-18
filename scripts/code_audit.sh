#!/usr/bin/env bash
# 后端代码巡检：低质量代码 / 冗余信息。定期执行入口（cron 每周调用）。
# 用法: bash scripts/code_audit.sh   （任意位置运行均可，内部自 cd 仓库根）
# 命中 P0（未定义名 / 不可达代码）时退出码 1，便于后续接 CI。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
PY=.venv/bin/python

echo "=== 1) P0 潜在 bug ==="
echo "-- F821 未定义名（运行时会炸）--"
$PY -m ruff check app tests --select F821 --output-format=concise 2>/dev/null | grep F821
echo "-- 不可达代码 / 死变量 --"
uvx vulture app --min-confidence 80 2>/dev/null | grep -E "unreachable|unused variable"

echo "=== 2) 冗余 ==="
N=$($PY -m ruff check app tests --select F401 --output-format=concise 2>/dev/null | grep -c F401)
echo "未用 import (F401): $N"
N=$($PY -m ruff check app tests --select F841 --output-format=concise 2>/dev/null | grep -c F841)
echo "未用变量 (F841): $N"
N=$(uvx pylint --disable=all --enable=R0801 app 2>/dev/null | grep -c "R0801")
echo "重复代码块 (pylint R0801): $N"

echo "=== 3) 低质量标记 ==="
N=$(grep -rn "TODO\|FIXME\|HACK" app --include=*.py | wc -l | tr -d ' ')
echo "TODO/FIXME/HACK: $N"
N=$(grep -rn "breakpoint()\|import pdb\|print(\"DEBUG\|print('DEBUG" app --include=*.py | wc -l | tr -d ' ')
echo "调试残留: $N"

echo "=== 4) 越积越多的本地杂物（未进 git，应定期清）==="
echo "tasks/ 条目: $(ls tasks 2>/dev/null | wc -l | tr -d ' ')"
echo "logs/runs: $(ls logs/runs 2>/dev/null | wc -l | tr -d ' ')"
echo "根目录 lgc*.json: $(ls lgc*.json 2>/dev/null | wc -l | tr -d ' ')"

echo "=== 5) 旧式标注（ruff --fix 可自动修）==="
$PY -m ruff check app tests --select UP006,UP045,UP035,I001 --statistics 2>/dev/null | head -5

echo "=== 6) git 未跟踪的垃圾文件（应进 .gitignore 或删除）==="
git status --short | grep "^??" | head -10
echo "（以上为巡检摘要；对比上次运行看趋势，只报新增/恶化即可）"

# 退出码：P0（未定义名 / 不可达代码）> 0 → 1，便于后续接 CI / 告警
P0=$($PY -m ruff check app tests --select F821 --output-format=concise 2>/dev/null | grep -c F821)
P0=$((P0 + $(uvx vulture app --min-confidence 80 2>/dev/null | grep -c unreachable)))
if [ "$P0" -gt 0 ]; then
  echo ">>> P0 合计 $P0 项（未定义名/不可达代码），退出码 1"
  exit 1
fi
echo ">>> P0 为 0，退出码 0"
exit 0
