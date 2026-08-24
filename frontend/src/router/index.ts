import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/LoginView.vue') },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '工作台' } },
        { path: 'kbs', component: () => import('../views/KbListView.vue'), meta: { title: '知识库' } },
        { path: 'documents', component: () => import('../views/DocumentsView.vue'), meta: { title: '文档管理' } },
        { path: 'chunks', component: () => import('../views/ChunksView.vue'), meta: { title: '切分块' } },
        { path: 'graph', component: () => import('../views/GraphView.vue'), meta: { title: '知识图谱' } },
        { path: 'search', component: () => import('../views/SearchView.vue'), meta: { title: '检索调试台' } },
        { path: 'chat', component: () => import('../views/ChatView.vue'), meta: { title: '对话测试台' } },
        { path: 'keys', component: () => import('../views/KeysView.vue'), meta: { title: '密钥管理' } },
        { path: 'audit', component: () => import('../views/AuditView.vue'), meta: { title: '审计日志' } },
        { path: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置' } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.path !== '/login' && !auth.token) return '/login'
  if (to.path === '/login' && auth.token) return '/dashboard'
  if (auth.token && !auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return '/login'
    }
  }
  return true
})

export default router
