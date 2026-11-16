---
name: general_response
description: 当其他技能都不适用时使用此技能。用于回答问题、解释概念、提供建议等通用对话场景。
version: 1.0.0
author: system
tags:
  - chat
  - response
  - conversation
risk: read
timeout: 60
retry: 0
stage: both
operation_targets:
  "*": [input]
usage: "必填 input（用户输入/问题正文）；context 可选。参数键必须是 input/context，不要用 message 等别名。"
parameters:
  type: object
  properties:
    input:
      type: string
      description: "用户输入"
      required: true
    context:
      type: string
      description: "上下文信息"
      required: false
---

# General Response Skill

## 功能描述

通用对话响应，用于问答、解释等场景。

### 适用场景

- 回答用户问题
- 解释技术概念
- 提供建议和帮助
- 一般性对话

## 调用示例

```json
{
  "input": "什么是 Python 的异步编程？",
  "context": "用户正在学习 Python"
}
```

## 返回格式

```json
{
  "success": true,
  "data": {
    "response": "Python 的异步编程是..."
  }
}
```
