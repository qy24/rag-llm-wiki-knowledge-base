import { defineStore } from 'pinia'
import client from '../api/client'
import type { UserInfo } from '../api/types'

export const useAuthStore = defineStore('auth', {
  getters: {
    isAdmin: (state) => state.user?.role === 'admin',
  },
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: null as UserInfo | null,
  }),
  actions: {
    async login(username: string, password: string) {
      const { data } = await client.post('/admin/login', { username, password })
      this.token = data.access_token
      localStorage.setItem('token', this.token)
      await this.fetchMe()
    },
    async fetchMe() {
      const { data } = await client.get('/admin/me')
      this.user = data
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
    },
  },
})

