<script setup lang="ts">
import { ref } from 'vue'
import { RouterView, useRouter } from 'vue-router'

const router = useRouter()
const isSidebarOpen = ref(true)

const navItems = [
  { path: '/', label: '首页', icon: '🏠' },
  { path: '/charts', label: '行情图表', icon: '📈' },
  { path: '/signals', label: '交易信号', icon: '📣' },
  { path: '/backtest', label: '策略回测', icon: '🧪' },
  { path: '/risk', label: '风险控制', icon: '🛡️' },
  { path: '/account', label: '账户信息', icon: '👤' }
]

const currentPath = () => router.currentRoute.value.path
</script>

<template>
  <div class="flex h-screen bg-gray-100">
    <!-- 侧边栏 -->
    <aside 
      class="bg-white shadow-lg transition-all duration-300 flex flex-col"
      :class="isSidebarOpen ? 'w-64' : 'w-16'"
    >
      <!-- Logo -->
      <div class="p-4 border-b border-gray-200">
        <div class="flex items-center">
          <span class="text-2xl mr-3">📊</span>
          <span v-if="isSidebarOpen" class="text-xl font-bold text-gray-800">期货分析</span>
        </div>
      </div>

      <!-- 导航菜单 -->
      <nav class="flex-1 p-4">
        <ul class="space-y-2">
          <li v-for="item in navItems" :key="item.path">
            <router-link 
              :to="item.path"
              class="flex items-center px-4 py-3 rounded-lg transition-colors"
              :class="currentPath() === item.path 
                ? 'bg-blue-500 text-white' 
                : 'text-gray-600 hover:bg-gray-100'"
            >
              <span class="text-xl mr-3">{{ item.icon }}</span>
              <span v-if="isSidebarOpen" class="font-medium">{{ item.label }}</span>
            </router-link>
          </li>
        </ul>
      </nav>

      <!-- 收起按钮 -->
      <div class="p-4 border-t border-gray-200">
        <button 
          @click="isSidebarOpen = !isSidebarOpen"
          class="w-full flex items-center justify-center py-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <span>{{ isSidebarOpen ? '◀' : '▶' }}</span>
        </button>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="flex-1 overflow-auto">
      <!-- 顶部导航栏 -->
      <header class="bg-white shadow-sm px-6 py-4 flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-800">
            {{ navItems.find(item => item.path === currentPath())?.label || '期货分析系统' }}
          </h1>
          <p class="text-sm text-gray-500">
            {{ new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }) }}
          </p>
        </div>
        <div class="flex items-center gap-4">
          <div class="relative">
            <input 
              type="text" 
              placeholder="搜索..."
              class="w-64 px-4 py-2 pl-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <span class="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400">🔍</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-3 h-3 bg-green-500 rounded-full animate-pulse"></span>
            <span class="text-sm text-gray-600">在线</span>
          </div>
        </div>
      </header>

      <!-- 页面内容 -->
      <div class="p-6">
        <RouterView />
      </div>
    </main>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
}
</style>
