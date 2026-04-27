**技术选型**：Vue 3 (Composition API)，纯前端，数据存储在组件状态中。

**模块划分**：
1. `App.vue`：根组件，承载状态与主逻辑。
2. `TodoInput.vue`：负责新增待办事项的输入组件。
3. `TodoList.vue`：负责展示和操作待办事项列表的组件。
4. `TodoFilter.vue`：负责筛选状态切换的组件。

**关键接口（状态与事件）**：
- 状态（在App中管理）：`todos` (Array)， `filter` (String: 'all'/'active'/'completed')。
- 事件：`add-todo`, `toggle-todo`, `delete-todo`, `change-filter`。

STAGE_DONE: architecture