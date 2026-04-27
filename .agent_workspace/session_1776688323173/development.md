### 1. 创建主应用组件 `src/App.vue`
```vue
<template>
  <div class="app">
    <header class="header">
      <h1>Vue3 TodoList</h1>
    </header>
    <main class="main">
      <!-- 输入区域 -->
      <div class="input-area">
        <input
          v-model="newTodo"
          @keyup.enter="addTodo"
          type="text"
          placeholder="What needs to be done?"
          class="todo-input"
        />
        <button @click="addTodo" class="add-btn">Add</button>
      </div>

      <!-- 列表区域 -->
      <div class="todo-list">
        <div v-if="filteredTodos.length === 0" class="empty-tip">
          {{ getEmptyTip }}
        </div>
        <TodoItem
          v-for="todo in filteredTodos"
          :key="todo.id"
          :todo="todo"
          @toggle="toggleTodo"
          @delete="deleteTodo"
        />
      </div>

      <!-- 底部状态栏 -->
      <footer class="footer">
        <span class="todo-count">
          {{ remaining }} {{ remaining === 1 ? 'item' : 'items' }} left
        </span>
        <div class="filters">
          <button
            :class="{ active: filter === 'all' }"
            @click="filter = 'all'"
          >
            All
          </button>
          <button
            :class="{ active: filter === 'active' }"
            @click="filter = 'active'"
          >
            Active
          </button>
          <button
            :class="{ active: filter === 'completed' }"
            @click="filter = 'completed'"
          >
            Completed
          </button>
        </div>
        <button
          v-if="todos.some(todo => todo.completed)"
          @click="clearCompleted"
          class="clear-btn"
        >
          Clear completed
        </button>
      </footer>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import TodoItem from './components/TodoItem.vue'
import { useTodoStorage } from './composables/useTodoStorage'

// 使用组合式函数管理状态和持久化
const { todos, saveTodos } = useTodoStorage()

const newTodo = ref('')
const filter = ref('all')

// 计算属性
const remaining = computed(() => todos.value.filter(t => !t.completed).length)

const filteredTodos = computed(() => {
  switch (filter.value) {
    case 'active':
      return todos.value.filter(todo => !todo.completed)
    case 'completed':
      return todos.value.filter(todo => todo.completed)
    default:
      return todos.value
  }
})

const getEmptyTip = computed(() => {
  if (todos.value.length === 0) return 'No todos yet. Add one above!'
  if (filter.value === 'active') return 'No active todos.'
  if (filter.value === 'completed') return 'No completed todos.'
  return 'No todos match the filter.'
})

// 方法
const addTodo = () => {
  const text = newTodo.value.trim()
  if (text === '') return
  
  todos.value.push({
    id: Date.now(),
    text,
    completed: false
  })
  newTodo.value = ''
  saveTodos()
}

const toggleTodo = (id) => {
  const todo = todos.value.find(t => t.id === id)
  if (todo) {
    todo.completed = !todo.completed
    saveTodos()
  }
}

const deleteTodo = (id) => {
  const index = todos.value.findIndex(t => t.id === id)
  if (index !== -1) {
    todos.value.splice(index, 1)
    saveTodos()
  }
}

const clearCompleted = () => {
  todos.value = todos.value.filter(todo => !todo.completed)
  saveTodos()
}

// 监听todos变化并保存
watch(todos, saveTodos, { deep: true })
</script>

<style scoped>
.app {
  max-width: 600px;
  margin: 0 auto;
  padding: 20px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
}

.header {
  text-align: center;
  margin-bottom: 30px;
}

.header h1 {
  color: #2c3e50;
  font-size: 2.5rem;
  font-weight: 300;
}

.main {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  padding: 20px;
}

.input-area {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.todo-input {
  flex: 1;
  padding: 12px 15px;
  border: 2px solid #e0e0e0;
  border-radius: 6px;
  font-size: 16px;
  transition: border-color 0.3s;
}

.todo-input:focus {
  outline: none;
  border-color: #3498db;
}

.add-btn {
  padding: 12px 24px;
  background: #3498db;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.3s;
}

.add-btn:hover {
  background: #2980b9;
}

.todo-list {
  min-height: 200px;
}

.empty-tip {
  text-align: center;
  padding: 40px 20px;
  color: #95a5a6;
  font-style: italic;
}

.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 20px;
  padding-top: 15px;
  border-top: 1px solid #eee;
  color: #777;
  font-size: 14px;
}

.filters {
  display: flex;
  gap: 5px;
}

.filters button {
  padding: 5px 10px;
  border: 1px solid transparent;
  background: none;
  border-radius: 4px;
  cursor: pointer;
  color: #777;
}

.filters button:hover {
  border-color: #eee;
}

.filters button.active {
  border-color: #3498db;
  color: #3498db;
}

.clear-btn {
  padding: 5px 10px;
  border: 1px solid #eee;
  background: none;
  border-radius: 4px;
  cursor: pointer;
  color: #777;
}

.clear-btn:hover {
  color: #e74c3c;
  border-color: #e74c3c;
}

.todo-count {
  font-weight: 500;
}
</style>
```

### 2. 创建待办事项组件 `src/components/TodoItem.vue`
```vue
<template>
  <div class="todo-item" :class="{ completed: todo.completed }">
    <div class="todo-content">
      <input
        type="checkbox"
        :checked="todo.completed"
        @change="$emit('toggle', todo.id)"
        class="todo-checkbox"
      />
      <span class="todo-text">{{ todo.text }}</span>
    </div>
    <button @click="$emit('delete', todo.id)" class="delete-btn" title="Delete">
      ×
    </button>
  </div>
</template>

<script setup>
defineProps({
  todo: {
    type: Object,
    required: true
  }
})

defineEmits(['toggle', 'delete'])
</script>

<style scoped>
.todo-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px;
  border-bottom: 1px solid #eee;
  transition: all 0.3s;
}

.todo-item:last-child {
  border-bottom: none;
}

.todo-item:hover {
  background: #f9f9f9;
}

.todo-content {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.todo-checkbox {
  width: 20px;
  height: 20px;
  cursor: pointer;
}

.todo-text {
  font-size: 16px;
  color: #333;
  transition: all 0.3s;
}

.todo-item.completed .todo-text {
  text-decoration: line-through;
  color: #95a5a6;
}

.delete-btn {
  width: 30px;
  height: 30px;
  border: none;
  background: none;
  color: #ccc;
  font-size: 24px;
  cursor: pointer;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.delete-btn:hover {
  color: #e74c3c;
  background: #fee;
}
</style>
```

### 3. 创建持久化组合式函数 `src/composables/useTodoStorage.js`
```javascript
import { ref, onMounted } from 'vue'

const STORAGE_KEY = 'vue3-todos'

export function useTodoStorage() {
  const todos = ref([])

  // 从localStorage加载数据
  const loadTodos = () => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      try {
        todos.value = JSON.parse(stored)
      } catch (e) {
        console.error('Failed to parse todos from localStorage:', e)
        todos.value = []
      }
    }
  }

  // 保存数据到localStorage
  const saveTodos = () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(todos.value))
  }

  // 组件挂载时加载数据
  onMounted(() => {
    loadTodos()
  })

  return {
    todos,
    saveTodos,
    loadTodos
  }
}
```

### 4. 更新入口文件 `src/main.js`
```javascript
import { createApp } from 'vue'
import App from './App.vue'

createApp(App).mount('#app')
```

### 5. 更新HTML模板 `index.html`
```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Vue3 TodoList</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

### 6. 添加全局样式 `src/style.css`
```css
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  min-height: 100vh;
  padding: 20px;
}

#app {
  min-height: 100vh;
}
```

### 7. 安装依赖并运行
```bash
cd vue3-todolist
npm install
npm run dev
```

STAGE_DONE: development