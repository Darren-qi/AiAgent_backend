---
name: file_operations
description: 当用户需要创建、读取、修改文件或目录时使用此技能。支持指定路径执行文件操作，可用于初始化项目结构、生成代码文件、保存任务结果等场景。
version: 1.0.0
author: system
tags:
  - file
  - io
  - project-init
parameters:
  type: object
  properties:
    operation:
      type: string
      description: "操作类型：create（创建项目结构）/ read / write / list / delete"
      required: true
      enum: [create, read, write, list, delete]
    path:
      type: string
      description: "文件或目录路径，建议使用相对路径如 ./project_name 或 ./my_file.py"
      required: true
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

### read - 读取文件

读取文件内容。

**参数：**
```json
{
  "operation": "read",
  "path": "./config.json"
}
```

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

## 路径规则

1. **相对路径**：相对于 `tasks/` 目录，即 `AiAgent/tasks/任务名/`
2. **绝对路径**：系统绝对路径（需通过安全检查）
3. **安全限制**：
   - 禁止操作 backend 目录
   - 禁止访问系统敏感路径

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
