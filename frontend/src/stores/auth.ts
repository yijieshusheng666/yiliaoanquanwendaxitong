import { defineStore } from 'pinia'
import * as authApi from '@/api/auth'
import { setToken, clearToken, setStoredUser, getStoredUser } from '@/api/http'

interface AuthState {
  user: { id: number; username: string; role?: string } | null
  initialized: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    user: null,
    initialized: false,
  }),
  getters: {
    isLoggedIn: (s) => s.user !== null,
    isAdmin: (s) => s.user?.role === 'admin',
    username: (s) => s.user?.username || '游客',
  },
  actions: {
    restore() {
      if (!this.initialized) {
        this.user = getStoredUser() ? { username: getStoredUser()!.username, id: 0, role: getStoredUser()!.role } : null
        this.initialized = true
      }
      return this.user
    },
    async login(username: string, password: string) {
      const res = await authApi.login(username, password)
      setToken(res.token)
      setStoredUser(res.user)
      this.user = { id: res.user.id, username: res.user.username, role: res.user.role }
    },
    async register(username: string, password: string) {
      const res = await authApi.register(username, password)
      setToken(res.token)
      setStoredUser(res.user)
      this.user = { id: res.user.id, username: res.user.username, role: res.user.role }
    },
    async logout() {
      try {
        await authApi.logout()
      } finally {
        clearToken()
        this.user = null
      }
    },
  },
})