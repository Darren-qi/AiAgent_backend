---
name: http_client
description: 当需要获取网页内容、调用外部 API 或进行网络请求时使用此技能。支持 GET/POST 请求，可用于爬取网页数据、调用第三方接口等场景。
version: 1.0.0
author: system
tags:
  - http
  - network
  - api
parameters:
  type: object
  properties:
    url:
      type: string
      description: "请求的 URL 地址"
      required: true
    method:
      type: string
      description: "HTTP 方法"
      default: GET
      enum: [GET, POST, PUT, DELETE]
      required: false
    headers:
      type: object
      description: "请求头"
      required: false
    data:
      type: object
      description: "POST 请求的数据体"
      required: false
    timeout:
      type: number
      description: "超时时间（秒）"
      default: 120
      required: false
---

# HTTP Client Skill

## 功能描述

发起 HTTP 请求获取网页内容或调用外部 API。

### 适用场景

- 爬取网页数据
- 调用第三方 API
- 获取远程配置
- 测试 API 接口

## 调用示例

### GET 请求
```json
{
  "url": "https://api.example.com/data",
  "method": "GET"
}
```

### POST 请求
```json
{
  "url": "https://api.example.com/submit",
  "method": "POST",
  "headers": {"Content-Type": "application/json"},
  "data": {"key": "value"}
}
```

## 返回格式

```json
{
  "success": true,
  "data": {
    "status": 200,
    "content": "响应内容..."
  }
}
```
