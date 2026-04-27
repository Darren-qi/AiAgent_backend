```
file_write(path="src/utils/storage.js", content={
  const STORAGE_KEY = 'vue3_todolist_data'

  const defaultData = {
    users: ['张三', '李四', '王五'],
    tasks: []
  }

  export function loadData() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        return JSON.parse(raw)
      }
    } catch (e) {
      console.error('读取本地数据失败', e)
    }
    return JSON.parse(JSON.stringify(defaultData))
  }

  export function saveData(data) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
    } catch (e) {
      console.error('保存本地数据失败', e)
    }
  }

  export function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substring(2, 8)
  }

  export function formatDate(dateStr) {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }
})
```

```
file_write(path="src/stores/userStore.js", content={
  import { defineStore } from 'pinia'
  import { ref, computed } from 'vue'
  import { loadData, saveData } from '../utils/storage'

  export const useUserStore = defineStore('user', () => {
    const data = loadData()
    const users = ref(data.users)
    const currentUser = ref(data.users[0] || '')

    const isLoggedIn = computed(() => currentUser.value !== '')

    function switchUser(username) {
      if (users.value.includes(username)) {
        currentUser.value = username
      }
    }

    function addUser(username) {
      if (!users.value.includes(username)) {
        users.value.push(username)
        saveData({ users: users.value, tasks: loadData().tasks })
      }
    }

    return { users, currentUser, isLoggedIn, switchUser, addUser }
  })
})
```

```
file_write(path="src/stores/taskStore.js", content={
  import { defineStore } from 'pinia'
  import { ref, computed } from 'vue'
  import { loadData, saveData, generateId, formatDate } from '../utils/storage'
  import { useUserStore } from './userStore'

  export const useTaskStore = defineStore('task', () => {
    const data = loadData()
    const tasks = ref(data.tasks)

    const userStore = useUserStore()

    // 当前用户的任务列表
    const userTasks = computed(() => {
      return tasks.value.filter(t => t.userId === userStore.currentUser)
    })

    // 按状态筛选
    const filteredTasks = computed(() => {
      let list = userTasks.value
      if (filterStatus.value !== 'all') {
        list = list.filter(t => t.status === filterStatus.value)
      }
      // 排序：先按优先级，再按截止日期
      const priorityOrder = { high: 0, medium: 1, low: 2 }
      list.sort((a, b) => {
        if (sortBy.value === 'priority') {
          const pa = priorityOrder[a.priority] || 1
          const pb = priorityOrder[b.priority] || 1
          return pa - pb
        }
        if (sortBy.value === 'dueDate') {
          if (!a.dueDate) return 1
          if (!b.dueDate) return -1
          return new Date(a.dueDate) - new Date(b.dueDate)
        }
        return 0
      })
      return list
    })

    const filterStatus = ref('all')
    const sortBy = ref('priority')
    const loading = ref(false)

    function addTask(taskData) {
      const newTask = {
        id: generateId(),
        userId: userStore.currentUser,
        title: taskData.title,
        description: taskData.description || '',
        status: 'todo',
        priority: taskData.priority || 'medium',
        dueDate: taskData.dueDate || '',
        createdAt: new Date().toISOString().split('T')[0]
      }
      tasks.value.push(newTask)
      saveToStorage()
    }

    function updateTask(taskId, updates) {
      const index = tasks.value.findIndex(t => t.id === taskId)
      if (index !== -1) {
        tasks.value[index] = { ...tasks.value[index], ...updates }
        saveToStorage()
      }
    }

    function deleteTask(taskId) {
      tasks.value = tasks.value.filter(t => t.id !== taskId)
      saveToStorage()
    }

    function changeStatus(taskId, newStatus) {
      updateTask(taskId, { status: newStatus })
    }

    function saveToStorage() {
      saveData({ users: userStore.users, tasks: tasks.value })
    }

    // 获取单个任务详情
    function getTaskById(taskId) {
      return tasks.value.find(t => t.id === taskId)
    }

    return {
      tasks,
      userTasks,
      filteredTasks,
      filterStatus,
      sortBy,
      loading,
      addTask,
      updateTask,
      deleteTask,
      changeStatus,
      getTaskById
    }
  })
})
```

STAGE_DONE: development

【工具执行结果】
✅ 文件写入成功：src/utils/storage.js
✅ 文件写入成功：src/stores/userStore.js
✅ 文件写入成功：src/stores/taskStore.js