import { defineStore } from 'pinia'
import { request, setToken } from '../api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null, initialized: false }),
  actions: {
    async login(username, password, captcha) {
      const data = await request('/api/auth/login', { method: 'POST', body: { username, password, captcha } })
      setToken(data.token || null)
      this.user = data.user
      this.initialized = true
      return data.user
    },
    async register(username, password, email, captcha) {
      const data = await request('/api/auth/register', { method: 'POST', body: { username, password, email, captcha } })
      setToken(data.token || null)
      this.user = data.user
      this.initialized = true
      return data.user
    },
    async loadMe() {
      try {
        this.user = await request('/api/auth/me')
      } catch {
        setToken(null)
        this.user = null
      } finally {
        this.initialized = true
      }
    },
    async ensureLoaded() {
      if (!this.initialized) await this.loadMe()
      return this.user
    },
    async updateProfile(profile) {
      this.user = await request('/api/user/profile', { method: 'PUT', body: profile })
      return this.user
    },
    async logout() {
      try {
        await request('/api/auth/logout', { method: 'POST' })
      } catch {
        // Local logout still clears client state if the session is already gone.
      }
      setToken(null)
      this.user = null
      this.initialized = true
    }
  }
})
