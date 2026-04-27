**技术栈选择：**
- **构建工具**: Vite (开发体验好，构建速度快)
- **前端框架**: Vue 3 (Composition API)
- **开发语言**: TypeScript (提升代码质量和开发体验)
- **状态管理**: Pinia (Vue官方推荐，轻量且类型安全)
- **UI组件库**: Element Plus (组件丰富，设计精美，易于二次封装)
- **CSS方案**: Sass/SCSS (便于编写模块化样式)

**架构分层思路：**
1. **视图层 (Views)**: 页面级组件，如TodoList主页面。
2. **组件层 (Components)**: 封装的通用UI组件和业务组件。
3. **状态层 (Stores)**: 使用Pinia管理TodoList的全局状态（任务列表、过滤条件等）。
4. **工具层 (Utils)**: 放置辅助函数、常量等。

**关键设计决策：**
1. 使用`create-vue`脚手架快速初始化项目，确保最佳实践。
2. 在`components/common`目录下封装基于Element Plus的常用组件（如`BaseButton`、`BaseInput`）。
3. TodoList的核心状态（任务增删改查）由Pinia Store管理，确保逻辑清晰且可复用。
4. 使用SCSS编写组件样式，并定义一套主题变量（如颜色、间距）以保证设计一致性。

STAGE_DONE: architecture