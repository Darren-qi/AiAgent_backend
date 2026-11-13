#!/usr/bin/env python3
"""黄金测试集运行器（Golden Test Set Runner）。

用法:
    .venv/bin/python run_golden.py          # 全量跑，禁止新增失败
    .venv/bin/python run_golden.py --fast   # 跳过真实 LLM 测试（提交前快验）

规则（2026-11-13 用户制定）:
  1. 发现新问题 = 先补测试用例进黄金集，再修，修完全绿才算完;
  2. 每次改动跑全部测试，不允许"改一个坏一处";
  3. tests/golden_allowlist.txt 是唯一允许失败清单（必须写原因）;
  4. 清单里的用例若转绿，本运行器会提示从清单移除。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALLOWLIST = ROOT / "tests" / "golden_allowlist.txt"
LLM_TESTS = [  # --fast 时跳过：依赖真实 LLM，慢且有偶发波动
    "tests/test_agent/test_agent.py::TestAgentGraph::test_execute_creates_flask_blog",
]


def load_allowlist() -> dict:
    allowed = {}
    if ALLOWLIST.exists():
        for line in ALLOWLIST.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            nodeid = line.split("#")[0].strip()
            reason = line.split("#", 1)[1].strip() if "#" in line else ""
            allowed[nodeid] = reason
    return allowed


def main() -> int:
    fast = "--fast" in sys.argv
    cmd = [sys.executable, "-m", "pytest", "tests/", "-q"]
    if fast:
        for t in LLM_TESTS:
            cmd += ["--deselect", t]
    print(f"[golden] running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = proc.stdout
    print(out[-4000:])

    failed = [l.split(" - ")[0].strip() for l in out.splitlines() if l.startswith("FAILED")]
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) skipped", out)
    skipped = int(m.group(1)) if m else 0

    allowed = load_allowlist()
    new_failures = [f for f in failed if f not in allowed]
    recovered = [a for a in allowed if a not in failed]

    print(f"[golden] passed={passed} skipped={skipped} failed={len(failed)} allowlisted={len(failed) - len(new_failures)}")
    if recovered:
        print("[golden] 清单内用例已转绿，请从 tests/golden_allowlist.txt 移除:")
        for r in recovered:
            print(f"  - {r}")
    if new_failures:
        print(f"[golden] ❌ 新增失败 {len(new_failures)} 个（黄金集不允许）:")
        for f in new_failures:
            print(f"  - {f}")
        print("[golden] 新问题处理流程: 先补测试用例 -> 修复 -> 本运行器全绿")
        return 1
    print("[golden] ✅ 全绿（无新增失败）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
