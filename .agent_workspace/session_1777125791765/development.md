```
project_create("vue3_todolist")
```

```
file_write(path="package.json", content={
  "name": "vue3-todolist",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.0.0"
  }
})
```

```
file_write(path="vite.config.js", content={
  import { defineConfig } from 'vite'
  import vue from '@vitejs/plugin-vue'

  export default defineConfig({
    plugins: [vue()],
    server: {
      port: 3000,
      open: true
    }
  })
})
```

```
file_write(path="index.html", content={
  <!DOCTYPE html>
  <html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>TODO List - 多用户任务管理</title>
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
  </html>
})
```

```
file_write(path="src/main.js", content={
  import { createApp } from 'vue'
  import { createPinia } from 'pinia'
  import router from './router'
  import App from './App.vue'

  const app = createApp(App)

  app.use(createPinia())
  app.use(router)

  app.mount('#app')
})
```

```
file_write(path="src/router/index.js", content={
  import { createRouter, createWebHistory } from 'vue-router'
  import TaskListView from '../views/TaskListView.vue'

  const routes = [
    {
      path: '/',
      name: 'tasks',
      component: TaskListView
    }
  ]

  const router = createRouter({
    history: createWebHistory(),
    routes
  })

  export default router
})
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'vue3_todolist'