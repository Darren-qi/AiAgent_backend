**技术栈选择**：Vue 3 (Composition API) + Pinia + Vite (构建工具) + TypeScript (可选，推荐)。

**架构分层思路**：
1.  **状态层 (Store)**：使用Pinia管理全局的待办事项列表状态（增、删、改、查、切换状态）。
2.  **视图/组件层 (Components)**：`App.vue`作为根组件，包含输入组件`TodoInput.vue`和列表展示组件`TodoList.vue`/`TodoItem.vue`。
3.  **工具/服务层 (Utils/Services)**：封装对`localStorage`的操作，提供数据持久化服务，供Pinia Store调用。

**数据库选型**：无需后端数据库。使用浏览器的`localStorage`或`IndexedDB`进行前端数据持久化。对于TodoList，`localStorage`完全足够。

**关键设计决策**：
1.  **状态管理**：使用Pinia而非Vuex，更轻量且对Composition API支持更好。
2.  **数据流**：组件通过调用Pinia Store的Actions来修改状态，Store的Actions负责同步更新`localStorage`。
3.  **组件设计**：遵循单一职责原则，将输入、列表项拆分为独立组件。

STAGE_DONE: architecture