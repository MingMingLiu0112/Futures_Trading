import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue')
  },
  {
    path: '/charts',
    name: 'Charts',
    component: () => import('../views/Charts.vue')
  },
  {
    path: '/signals',
    name: 'Signals',
    component: () => import('../views/Signals.vue')
  },
  {
    path: '/backtest',
    name: 'Backtest',
    component: () => import('../views/Backtest.vue')
  },
  {
    path: '/risk',
    name: 'Risk',
    component: () => import('../views/Risk.vue')
  },
  {
    path: '/account',
    name: 'Account',
    component: () => import('../views/Account.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
