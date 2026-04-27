**技术栈选择：**
- 框架：Vue 3 (Composition API + `<script setup>`)
- 状态管理：Pinia（管理用户、任务数据）
- 路由：Vue Router（用户视图、任务详情视图）
- UI：原生CSS + 简单动画（无第三方UI库，保持轻量）
- 数据持久化：localStorage（模拟后端存储）

**架构分层：**
1. **视图层** — 页面组件：`UserView`（用户切换）、`TaskListView`（任务列表）、`TaskDetailView`（任务详情弹窗）
2. **状态层** — Pinia Store：`userStore`（当前用户、用户列表）、`taskStore`（任务CRUD、筛选排序逻辑）
3. **工具层** — `storage.js`（封装localStorage读写），`helpers.js`（日期格式化、ID生成）

**数据库选型：**
- 无需数据库，使用 localStorage 存储 JSON 数据，结构如下：
  ```json
  {
    "users": ["张三", "李四"],
    "tasks": [
      {
        "id": "uuid",
        "userId": "张三",
        "title": "完成报告",
        "description": "...",
        "status": "todo",
        "priority": "high",
        "dueDate": "2024-01-20",
        "createdAt": "2024-01-15"
      }
    ]
  }
  ```

**关键设计决策：**
- 用户切换即切换数据域，每个用户看到自己的任务
- 任务状态用枚举：`todo` → `in_progress` → `done`，支持双向切换
- 任务详情用弹窗（Modal）实现，不另开路由，保持交互流畅
- 数据变更后自动同步到localStorage，页面刷新不丢失

STAGE_DONE: architecture