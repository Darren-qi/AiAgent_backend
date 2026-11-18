---
name: file_operations
description: 当用户需要创建、读取、修改文件或目录时使用此技能。支持指定路径执行文件操作，可用于初始化项目结构、生成代码文件、保存任务结果等场景。
version: 1.0.0
author: system
tags:
  - file
  - io
  - project-init
risk: write
op_semantics:
  read: idempotent
  list: idempotent
  write: idempotent
  create: once
  edit: conditional
  move: conditional
  delete: conditional
path_arg: path
timeout: 60
retry: 0
stage: both
parameters:
  type: object
  properties:
    operation:
      type: string
      description: "操作类型：create（创建项目结构）/ read / write / edit / list / delete / move（移动归类）"
      required: true
      enum: [create, read, write, edit, list, delete, move]
    path:
      type: string
      description: "文件或目录路径，建议使用相对路径如 ./project_name 或 ./my_file.py"
      required: true
    dest:
      type: string
      description: "move 操作的目标路径（相对任务目录，如 backend/app.py），仅 move 时需要"
      required: false
    content:
      type: string
      description: "写入文件的内容（write/create 操作时必需）"
      required: false
    encoding:
      type: string
      description: "文件编码，默认 utf-8"
      default: utf-8
      required: false
    options:
      type: object
      description: "额外选项"
      required: false
      properties:
        recursive:
          type: boolean
          description: "是否递归创建目录"
          default: true
        mode:
          type: string
          description: "创建模式：file（单个文件）/ project（项目结构）"
          default: file
    old_text:
      type: string
      description: "edit 要替换的原文（须与文件内容逐字一致且唯一；命中多处时配 replace_all）"
      required: false
    new_text:
      type: string
      description: "edit 替换后的新文本"
      required: false
    replace_all:
      type: boolean
      description: "edit 命中多处时是否全部替换，默认 false"
      default: false
      required: false
    files:
      type: array
      description: "批量数组：write=[{path,content}]、read/delete=[{path}]、move=[{path,dest}]。单次≤4文件、总内容≤6000字，超出拆多次调用（防输出截断成残缺JSON）"
      required: false
    edits:
      type: array
      description: "批量编辑数组 [{path,old_text,new_text,replace_all?}]，一次完成多处/多文件修改，单次≤4文件"
      required: false
    paths:
      type: array
      description: "delete 的批量路径数组，与 path 二选一，如 [\"a.txt\", \"dir\"]"
      required: false
# 操作目标参数契约：params 缺这些键即结构崩坏，执行前拦截（validate_params_structure）
operation_targets:
  create: [path]
  write: [path, files]
  read: [path, files]
  edit: [path, edits]
  list: []
  delete: [path, files, paths]
  move: [path, files, from, src]
# 出错 JIT 时随全量参数 schema 一起注入（第三级：选定工具后的具体使用方法）
# 也是规划 prompt 参数段的唯一权威（阶段四试点：prompt 硬编码段改为引用本字段）
usage: "params 必须是 JSON 对象且键必须是已声明参数；path 必须是合法文件路径（如 app.py、routes/__init__.py），不能是 Python 代码（如 @app.route('/')）；目标参数按 operation 必选其一：write/read→path 或 files[]，edit→path 或 edits[]，delete→path、files[] 或 paths[]，move→path 或 files[]，list/create→path。批量单次≤4文件、总内容≤6000字，超出拆多次调用。缺目标参数被拦时补 path 或改用 files 批量，禁止把大段文件内容塞进单个参数。"
---

# File Operations Skill

## 功能描述

该技能提供文件系统的基本操作能力，是 Agent 完成任务的基础工具。

### 适用场景

- 初始化项目结构（create 操作）
- 生成代码文件（write 操作）
- 读取配置文件或代码（read 操作）
- 查看目录结构（list 操作）
- 删除不需要的文件（delete 操作）
- 移动/归类/整理文件到指定目录（move 操作）

## 操作详解

### create - 创建项目结构

用于初始化新项目，自动创建目录和基础文件。

**参数：**
```json
{
  "operation": "create",
  "path": "./my_flask_app_18468123",
  "content": "文件名:内容\n文件名2:内容2",
  "options": {"recursive": true}
}
```

**content 格式：** 使用 `文件名:内容` 的格式支持多文件批量创建，每行一个文件。

### write - 写入文件

覆盖或创建单个文件。

**参数：**
```json
{
  "operation": "write",
  "path": "./app.py",
  "content": "from flask import Flask\napp = Flask(__name__)"
}
```

**批量写入（互不依赖的新建文件一次并发建完，替代逐文件多轮）：**

⚠️ **单次批量写控制规模**：≤4 个文件或总内容 ≤6000 字，超出分多轮发——单次参数过长会被输出上限截断成残缺 JSON，整批失败只能下轮重来（2026-11-13 TC-S16-01 生产取证）。
```json
{
  "operation": "write",
  "files": [
    {"path": "config.py", "content": "..."},
    {"path": "app/__init__.py", "content": "..."},
    {"path": "requirements.txt", "content": "Flask>=3.0"}
  ]
}
```
- 提供 `files` 数组时忽略 `path`/`content`；子目录自动创建
- 并发执行，单个文件失败不影响其余；结果返回 `files`（成功清单）、`count`，有失败时附 `note`

### read - 读取文件

读取文件内容。

**参数：**
```json
{
  "operation": "read",
  "path": "./config.json"
}
```

**并行批量读取（与 write 的 files 对称）：**
```json
{
  "operation": "read",
  "files": [{"path": "config.py"}, {"path": "app/__init__.py"}]
}
```
- 返回 `content` 为各文件拼接（`=== 路径 ===` 分隔），`files` 为成功清单

### edit - 局部替换文件内容

按精确原文替换（old 必须与文件内容逐字一致，不接受近似/正则）。

**参数：**
```json
{"operation": "edit", "path": "app.py", "old": "旧代码", "new": "新代码"}
```

**批量替换（edits 数组，一次调用完成多处/多文件修改）：**
```json
{
  "operation": "edit",
  "path": "app.py",
  "edits": [
    {"old": "片段1", "new": "新1"},
    {"old_text": "片段2", "new_text": "新2"},
    {"path": "b.py", "old": "x", "new": "y"}
  ]
}
```
- 每项可带 `path`（缺省用顶层 `path`），键名 `old/new` 或 `old_text/new_text` 均可
- 同文件多处按数组顺序应用；`replace_all` 默认 false

### list - 列出目录

查看目录内容和结构。

**参数：**
```json
{
  "operation": "list",
  "path": "./my_project"
}
```

### delete - 删除文件/目录

删除文件或目录（递归删除目录）。

**参数：**
```json
{
  "operation": "delete",
  "path": "./temp_folder"
}
```

**批量删除**（清理残留一次删多个）：
```json
{
  "operation": "delete",
  "files": [{"path": "a.txt"}, {"path": "old_dir"}]
}
```
也接受 `paths=["a.txt", "old_dir"]`（字符串列表）；单个失败进 note 不中断，全部失败才报错。

### move - 移动/归类文件或目录

把文件从源位置搬到目标位置：**移动后原位置不再有该文件**（原子移动，不是复制）。
归类、整理、迁移、"统一放到 xx 目录"类任务必须用 move；在目标位置用 write 重新生成一份不算移动。

**参数：**
```json
{
  "operation": "move",
  "path": "./main.py",
  "dest": "backend/main.py"
}
```

- `path` = 源路径，`dest` = 目标路径（均为相对任务目录的路径）
- 目标已存在时按 shell mv 语义覆盖（源是要移动的权威文件）；目录冲突才拒绝
- 源目录被搬空时会**自动删除该空目录**（非空则保留）；删除文件后父目录变空同样自动清理

**批量移动**（归类/重构一次搬多个，别分多轮逐个搬）：
```json
{
  "operation": "move",
  "files": [
    {"path": "app/main.py", "dest": "backend/app/main.py"},
    {"from": "config.py", "to": "backend/config.py"}
  ]
}
```
- 元素键兼容 `path/from/src/source` + `dest/destination/to/dst`（生产实测模型会混用）
- 串行执行，单个失败不影响其余；全部失败才返回失败

## 路径规则

1. **相对路径**：相对于 `tasks/` 目录，即 `AiAgent/tasks/任务名/`
2. **绝对路径**：系统绝对路径（需通过安全检查）
3. **先看结构再访问**：【任务目录现有文件】清单是本轮开始的快照，移动/新建后会过期——路径没把握时先 `operation=list` 看真实目录树，禁止臆测目录名

## 返回格式

```json
{
  "success": true,
  "data": {
    "path": "/实际写入路径",
    "size": 1234
  }
}
```

## 常见错误

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| 缺少 path 参数 | 未指定文件路径 | 必须提供 path 参数 |
| 安全检查失败 | 路径在禁止目录内 | 使用 tasks/ 目录下的路径 |
| 文件不存在 | read 操作的文件不存在 | 检查 path 是否正确 |
