---
name: search
description: 当用户需要搜索信息、查找资料或查询问题时使用此技能。可以搜索网络内容或利用 LLM 知识库回答问题。
version: 1.0.0
author: system
tags:
  - search
  - information
  - knowledge
parameters:
  type: object
  properties:
    query:
      type: string
      description: "搜索关键词或问题"
      required: true
    engine:
      type: string
      description: "搜索引擎"
      default: default
      enum: [default, google, baidu]
      required: false
    limit:
      type: number
      description: "返回结果数量"
      default: 5
      required: false
---

# Search Skill

## 功能描述

搜索信息或回答问题。

### 适用场景

- 搜索技术文档
- 查找解决方案
- 获取背景知识
- 回答开放性问题

## 调用示例

```json
{
  "query": "Python 异步编程教程",
  "engine": "default",
  "limit": 3
}
```

## 返回格式

```json
{
  "success": true,
  "data": {
    "query": "Python 异步编程教程",
    "results": [
      {"title": "...", "description": "...", "score": 0.9}
    ],
    "engine": "default"
  }
}
```
