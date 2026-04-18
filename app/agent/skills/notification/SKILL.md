---
name: notification
description: 当需要向用户发送通知、邮件或消息时使用此技能。支持邮件、飞书、企业微信、钉钉等渠道。
version: 1.0.0
author: system
tags:
  - notification
  - email
  - message
parameters:
  type: object
  properties:
    channel:
      type: string
      description: "通知渠道"
      default: email
      enum: [email, feishu, wecom, dingtalk]
      required: false
    recipient:
      type: string
      description: "接收人/接收地址"
      required: false
    title:
      type: string
      description: "通知标题"
      default: AiAgent 通知
      required: false
    content:
      type: string
      description: "通知内容"
      required: true
---

# Notification Skill

## 功能描述

发送通知到各种渠道。

### 适用场景

- 任务完成通知
- 错误告警通知
- 定期报告推送
- 团队消息通知

## 调用示例

```json
{
  "channel": "email",
  "recipient": "user@example.com",
  "title": "任务完成",
  "content": "您的 Flask 项目已创建完成..."
}
```

## 返回格式

```json
{
  "success": true,
  "data": {
    "sent": true,
    "channel": "email",
    "recipient": "user@example.com"
  }
}
```
