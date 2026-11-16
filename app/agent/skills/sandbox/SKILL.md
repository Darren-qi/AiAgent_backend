---
name: sandbox
description: 在隔离沙箱中运行 Python 代码或任务目录下的脚本文件（如运行 test_calculator.py），返回 stdout/stderr/returncode。生成测试或可执行脚本后必须用它实际运行验证，失败把错误输出带回下一步修正。
version: 1.0.0
author: system
tags:
  - sandbox
  - exec
  - test
risk: exec
timeout: 60
retry: 0
stage: execute
operation_targets:
  "*": [code, file]
usage: "code 与 file 二选一（file 为任务目录内相对路径）；timeout 默认 30 秒、最大 60。二者都缺被拦时补其一重发。"
parameters:
  type: object
  properties:
    code:
      type: string
      description: "要执行的完整 Python 源码（与 file 二选一）"
      required: false
    file:
      type: string
      description: "要运行的脚本相对路径（相对任务目录），如 test_calculator.py（与 code 二选一）"
      required: false
    timeout:
      type: integer
      description: "超时秒数，默认 30，最大 60"
      required: false
---

# Sandbox Skill

## 功能描述

在受限沙箱中执行 Python：运行生成的测试、验证脚本、计算逻辑。

### 适用场景

- 运行 unittest/pytest 测试文件，确认测试真的通过
- 执行脚本验证生成的代码可运行
- 需要实际运行结果作为待办完成证据

### 安全限制（不要试图绕过）

- 运行目录锁定在任务目录内；`file` 不允许指向任务目录外
- 无网络沙箱语义不保证（restricted 模式），不要执行与任务无关的代码
- 超时 30s（最大 60s）会被强杀；输出截断（stdout 8000 字符）

## 操作详解

### 运行脚本文件（推荐用于测试）
```json
{
  "file": "test_calculator.py",
  "timeout": 30
}
```

### 运行代码片段
```json
{
  "code": "print(1 + 1)"
}
```

## 返回格式

```json
{
  "success": true,
  "data": {
    "stdout": "...\n",
    "stderr": "",
    "returncode": 0,
    "workdir": "/.../tasks/auto_project_xxx",
    "provider": "restricted"
  }
}
```

失败时 `error` 形如 `exit_1: <stderr 尾部>`；测试没过就是 success=false，把错误带回下一步修复。
