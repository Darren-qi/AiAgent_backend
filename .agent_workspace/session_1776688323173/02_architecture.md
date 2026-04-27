**技术栈选择**：
- **框架**：Vue 3 (Composition API)
- **构建工具**：Vite (用于快速启动和开发)
- **状态管理**：使用Vue 3的 `reactive` 或 `ref` 进行组件内状态管理，无需引入Pinia/Vuex。
- **UI组件/样式**：无预设UI库，使用原生CSS或轻量级工具（如UnoCSS/Tailwind）按需引入。
- **持久化**：使用浏览器的 `localStorage`。

**架构分层思路**：
1.  **视图层 (View)**：由Vue单文件组件构成，负责UI渲染和用户交互。
2.  **状态/逻辑层 (State/Logic)**：在组件内部使用Composition API (`setup`或`<script setup>`) 集中管理待办事项列表的状态和核心业务逻辑（增、删、改、查、持久化）。

**关键设计决策**：
1.  数据流采用单向数据流，状态变更逻辑集中在组件逻辑层。
2.  持久化逻辑封装为独立的组合式函数（如 `useTodoStorage`），提高可测试性和复用性。
3.  组件结构保持扁平，一个主组件 (`App.vue`) 和可能的子组件（如 `TodoItem.vue`）即可。

STAGE_DONE: architecture