---
name: search_files
description: "在任务目录内按关键词搜索代码内容（正则，返回 文件:行号: 匹配行）或按文件名找文件。梳理/定位代码时优先用本技能，代替整读大文件和 list 目录逐层漫游。"
version: 1.0.0
author: system
tags:
  - search
  - code
  - files
risk: read
path_arg: path
timeout: 30
retry: 1
stage: both
operation_targets:
  "*": [pattern]
usage: "必填 pattern（content 模式为正则，files 模式为文件名 glob）；target 默认 content，path 默认任务目录根。缺 pattern 被拦时补检索式重发。"
parameters:
  type: object
  properties:
    pattern:
      type: string
      description: "正则表达式（target=content）或文件名 glob（target=files，如 *.py）"
      required: true
    target:
      type: string
      description: "content=搜文件内容；files=按文件名找文件"
      enum: [content, files]
      default: content
    path:
      type: string
      description: "搜索起始目录（相对任务目录，默认 . 即整个任务目录）"
      default: "."
    file_glob:
      type: string
      description: "只搜匹配的文件名（如 *.py、models*），可选"
    output_mode:
      type: string
      description: "content 模式输出格式：content=匹配行明细；files_only=仅文件列表；count=每文件命中数"
      enum: [content, files_only, count]
      default: content
    limit:
      type: number
      description: "最大返回条数（默认 50，上限 200）"
      default: 50
    offset:
      type: number
      description: "跳过前 N 条结果（翻页用，默认 0）"
      default: 0
---

# Search Files Skill

## 功能描述

任务目录内的代码搜索：关键词定位代替整读/漫游。

### 适用场景

- 想找"删除操作入口在哪"这类问题：`pattern: "delete|remove|destroy"` 秒级拿到 `文件:行号`
- 找文件：`target: files, pattern: "*.vue"`
- 探数量：`output_mode: count` 先看命中分布再决定取哪些

### 标准工作流（先搜后读）

1. `search_files` 定位 → 拿到 `文件:行号`
2. `file_operations` read 用 `offset=行号-10, limit=80` 精读命中点附近
3. 信息足够就推进产出，不要为"再确认"反复读

## 调用示例

```json
{"pattern": "def delete|remove\\(", "target": "content", "output_mode": "content"}
```

```json
{"pattern": "*.py", "target": "files"}
```

## 返回格式

```json
{
  "success": true,
  "data": {
    "matches": ["src/api.py:42: def delete_post(post_id):"],
    "total_matches": 7,
    "files_hit": 3,
    "has_more": false,
    "note": ""
  }
}
```
