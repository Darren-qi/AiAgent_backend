---
name: data_processor
description: 当需要对数据进行解析、转换、过滤、排序或统计分析时使用此技能。支持 JSON 数据处理、列表操作、聚合计算等功能。
version: 1.0.0
author: system
tags:
  - data
  - processing
  - transform
parameters:
  type: object
  properties:
    operation:
      type: string
      description: "操作类型"
      required: true
      enum: [parse_json, filter, sort, aggregate, transform]
    input_data:
      type: string
      description: "输入数据（JSON 字符串或对象）"
      required: true
    options:
      type: object
      description: "操作选项"
      required: false
---

# Data Processor Skill

## 功能描述

数据处理、转换、统计分析。

### 适用场景

- JSON 数据解析
- 数据过滤筛选
- 数据排序
- 数据聚合统计
- 数据格式转换

## 操作详解

### parse_json - 解析 JSON
```json
{
  "operation": "parse_json",
  "input_data": "{\"key\": \"value\"}"
}
```

### filter - 过滤数据
```json
{
  "operation": "filter",
  "input_data": [{"name": "Alice", "age": 25}, {"name": "Bob", "age": 30}],
  "options": {"field": "age", "operator": "gt", "value": 25}
}
```

### sort - 排序数据
```json
{
  "operation": "sort",
  "input_data": [3, 1, 2],
  "options": {"reverse": false}
}
```

### aggregate - 聚合统计
```json
{
  "operation": "aggregate",
  "input_data": [1, 2, 3, 4, 5],
  "options": {"type": "avg"}
}
```

### transform - 格式转换
```json
{
  "operation": "transform",
  "input_data": [{"id": 1, "name": "Alice"}],
  "options": {"type": "to_dict", "key_field": "id"}
}
```

## 返回格式

```json
{
  "success": true,
  "data": {
    "result": {...},
    "operation": "filter"
  }
}
```
