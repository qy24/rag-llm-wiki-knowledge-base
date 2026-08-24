<template>
  <el-container style="height: 100%">
    <el-aside width="200px" class="sidebar">
      <div class="sidebar-title">
        <span class="sidebar-logo">📚</span>
        <span class="sidebar-name">本地知识库系统</span>
      </div>
      <el-menu
        class="sidebar-menu"
        :default-active="activePath"
        router
        background-color="#001529"
        text-color="rgba(255,255,255,0.68)"
        active-text-color="#ffffff"
      >
        <el-menu-item v-for="item in menus" :key="item.path" :index="item.path">
          <span class="menu-text">{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">v0.1.0</div>
    </el-aside>
    <el-container>
      <el-header style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #eee; padding: 0 20px">
        <span style="font-size: 16px; font-weight: 600">{{ $route.meta.title }}</span>
        <span>
          <el-tag size="small" style="margin-right: 8px">{{ auth.user?.username || '' }}</el-tag>
          <el-button size="small" @click="logout">退出登录</el-button>
        </span>
      </el-header>
      <el-main style="padding: 0; overflow: auto">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const menus = [
  { path: '/dashboard', title: '工作台' },
  { path: '/kbs', title: '知识库管理' },
  { path: '/documents', title: '文档管理' },
  { path: '/chunks', title: '切分块管理' },
  { path: '/graph', title: '知识图谱' },
  { path: '/search', title: '检索调试台' },
  { path: '/chat', title: '对话测试台' },
  { path: '/keys', title: '密钥管理' },
  { path: '/audit', title: '审计日志' },
  { path: '/settings', title: '系统设置' },
]

const activePath = computed(() => route.path)

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #001529;
  overflow: hidden;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 56px;
  padding: 0 20px;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

.sidebar-logo {
  font-size: 18px;
}

.sidebar-name {
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-menu {
  flex: 1;
  overflow-y: auto;
  border-right: none;
}

.sidebar-menu :deep(.el-menu-item) {
  height: 46px;
  line-height: 46px;
  margin: 2px 8px;
  border-radius: 6px;
  padding-left: 16px !important;
}

.sidebar-menu :deep(.el-menu-item:hover) {
  background-color: rgba(255, 255, 255, 0.08);
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background-color: #409eff;
  color: #fff;
}

.sidebar-menu :deep(.el-menu-item.is-active .menu-text) {
  color: #fff;
}

.sidebar-footer {
  flex-shrink: 0;
  padding: 10px 0 14px;
  text-align: center;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
</style>
