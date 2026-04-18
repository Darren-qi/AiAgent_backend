---
name: code_generator
description: 当用户需要生成代码或创建程序文件时使用此技能。支持多种编程语言（Python/JavaScript/TypeScript/Go等），可根据需求描述生成完整的、可运行的代码。
version: 1.0.0
author: system
tags:
  - code
  - generator
  - programming
parameters:
  type: object
  properties:
    language:
      type: string
      description: "编程语言，如 python/js/ts/go/java"
      default: python
      required: false
    requirements:
      type: string
      description: "代码需求描述，详细说明需要实现的功能"
      required: true
    framework:
      type: string
      description: "框架，如 react/vue/fastapi/flask"
      required: false
---

# Code Generator Skill

## 功能描述

根据需求描述生成高质量代码，支持多种编程语言和框架。

### 适用场景

- 生成项目代码结构
- 创建特定功能的代码文件
- 生成 API 接口代码
- 生成前端组件代码

## 调用示例

### 生成 Flask 项目
```json
{
  "language": "python",
  "requirements": "创建一个简单的 Flask 博客系统，包含文章列表和详情页",
  "framework": "flask"
}
```

### 生成 React 组件
```json
{
  "language": "javascript",
  "requirements": "创建一个用户登录表单组件",
  "framework": "react"
}
```

## 输出规则

1. **路径规则**：只写相对于项目根目录的路径，不包含项目文件夹名
2. **禁止操作**：禁止在 backend/ 目录下创建文件
3. **质量要求**：代码简洁、规范、可直接运行

## 返回格式

```json
{
  "success": true,
  "data": {
    "language": "python",
    "code": "生成的代码...",
    "framework": "flask"
  }
}
```
