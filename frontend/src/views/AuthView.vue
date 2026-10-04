<template>
  <section class="auth-layout">
    <form class="panel auth-card" @submit.prevent="submit">
      <p class="eyebrow">账号</p>
      <h1>{{ mode === 'login' ? '登录云打印' : '注册账号' }}</h1>
      <label class="field-label">用户名</label>
      <input v-model="username" class="input" autocomplete="username" />
      <label v-if="mode === 'register'" class="field-label">邮箱</label>
      <input v-if="mode === 'register'" v-model="email" class="input" type="email" />
      <label class="field-label">密码</label>
      <input v-model="password" class="input" type="password" autocomplete="current-password" />
      <label class="field-label">验证码</label>
      <div class="captcha-row">
        <input v-model="captcha" class="input" autocomplete="off" inputmode="numeric" />
        <button class="captcha-button" type="button" :disabled="captchaLoading" @click="refreshCaptcha">
          <img v-if="captchaUrl" :src="captchaUrl" alt="验证码" />
          <span v-else class="captcha-placeholder">{{ captchaLoading ? '加载中' : '刷新验证码' }}</span>
        </button>
      </div>
      <div v-if="captchaError" class="field-hint warning">{{ captchaError }}</div>
      <div v-if="error" class="notice warning">{{ error }}</div>
      <button class="primary-btn full"><LogIn :size="18" />{{ mode === 'login' ? '登录' : '注册' }}</button>
      <button class="text-btn" type="button" @click="toggleMode">{{ mode === 'login' ? '没有账号？注册' : '已有账号？登录' }}</button>
    </form>

    <section v-if="showInitialRestore" class="panel auth-card restore-setup-card">
      <p class="eyebrow">初始化</p>
      <h2>从备份文件恢复</h2>
      <label :class="['restore-dropzone', { active: restoreDragging }]" @dragover.prevent="restoreDragging = true" @dragleave.prevent="restoreDragging = false" @drop.prevent="dropRestoreFile">
        <UploadCloud :size="28" />
        <span>拖拽备份文件到这里，或点击上传</span>
        <small>仅新安装或无业务数据时可用</small>
        <input type="file" accept=".zip,.tar.gz,.tgz" @change="chooseRestoreFile" />
      </label>
      <div v-if="restoreInfo" class="restore-confirm">
        <strong>{{ restoreInfo.filename }}</strong>
        <span>备份时间：{{ formatDateTime(restoreInfo.backup_time) }} · 数据版本：{{ restoreInfo.data_version }}</span>
        <button class="secondary-btn danger" :disabled="restoreBusy" @click="restoreBackup">确认恢复并刷新</button>
      </div>
      <div v-if="restoreError" class="notice warning">{{ restoreError }}</div>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { LogIn, UploadCloud } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { buildApiUrl, request } from '../api/client'

const auth = useAuthStore()
const router = useRouter()
const mode = ref('login')
const username = ref('')
const password = ref('')
const email = ref('')
const captcha = ref('')
const captchaUrl = ref('')
const captchaLoading = ref(false)
const captchaError = ref('')
const error = ref('')
const initialRestoreAvailable = ref(false)
const restoreStatusChecked = ref(false)
const restoreDragging = ref(false)
const restoreFile = ref(null)
const restoreInfo = ref(null)
const restoreBusy = ref(false)
const restoreError = ref('')
let captchaObjectUrl = ''
let captchaRequestId = 0
const CAPTCHA_TIMEOUT_MS = 8000
const showInitialRestore = computed(() => restoreStatusChecked.value && initialRestoreAvailable.value && !auth.user)

function revokeCaptchaUrl() {
  if (!captchaObjectUrl) return
  URL.revokeObjectURL(captchaObjectUrl)
  captchaObjectUrl = ''
}

async function refreshCaptcha() {
  captcha.value = ''
  const requestId = ++captchaRequestId
  captchaLoading.value = true
  captchaError.value = ''
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), CAPTCHA_TIMEOUT_MS)
  try {
    const response = await fetch(buildApiUrl(`/api/auth/captcha?t=${Date.now()}`), {
      credentials: 'include',
      cache: 'no-store',
      headers: { Accept: 'image/png' },
      signal: controller.signal
    })
    const contentType = response.headers.get('content-type') || ''
    if (!response.ok || !contentType.includes('image/png')) {
      throw new Error('验证码加载失败，请检查后端服务是否正常')
    }
    const nextUrl = URL.createObjectURL(await response.blob())
    if (requestId !== captchaRequestId) {
      URL.revokeObjectURL(nextUrl)
      return
    }
    revokeCaptchaUrl()
    captchaUrl.value = nextUrl
    captchaObjectUrl = nextUrl
  } catch (err) {
    if (requestId !== captchaRequestId) return
    revokeCaptchaUrl()
    captchaUrl.value = ''
    captchaError.value = err.name === 'AbortError'
      ? '验证码加载超时，请确认后端服务已启动'
      : err.message || '验证码加载失败，请稍后重试'
  } finally {
    window.clearTimeout(timeoutId)
    if (requestId === captchaRequestId) captchaLoading.value = false
  }
}

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
  refreshCaptcha()
}

async function submit() {
  try {
    if (mode.value === 'login') await auth.login(username.value, password.value, captcha.value)
    else await auth.register(username.value, password.value, email.value, captcha.value)
    router.push('/')
  } catch (err) {
    error.value = err.message
    refreshCaptcha()
  }
}

async function loadRestoreStatus() {
  restoreStatusChecked.value = false
  if (auth.user) {
    initialRestoreAvailable.value = false
    restoreStatusChecked.value = true
    return
  }
  try {
    const status = await request('/api/setup/restore/status')
    initialRestoreAvailable.value = Boolean(status.available)
  } catch {
    initialRestoreAvailable.value = false
  } finally {
    restoreStatusChecked.value = true
  }
}

async function chooseRestoreFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file) await inspectRestoreFile(file)
}

async function dropRestoreFile(event) {
  restoreDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) await inspectRestoreFile(file)
}

async function inspectRestoreFile(file) {
  restoreFile.value = file
  restoreInfo.value = null
  restoreError.value = ''
  const body = new FormData()
  body.append('file', file)
  try {
    restoreInfo.value = await request('/api/setup/restore/inspect', { method: 'POST', body })
  } catch (err) {
    restoreError.value = err.message
  }
}

async function restoreBackup() {
  if (!restoreFile.value || !restoreInfo.value) return
  if (!window.confirm(`确认用 ${restoreInfo.value.filename} 恢复系统数据？`)) return
  restoreBusy.value = true
  restoreError.value = ''
  const body = new FormData()
  body.append('file', restoreFile.value)
  try {
    await request('/api/setup/restore', { method: 'POST', body })
    window.location.reload()
  } catch (err) {
    restoreError.value = err.message
  } finally {
    restoreBusy.value = false
  }
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

onMounted(() => {
  refreshCaptcha()
  loadRestoreStatus()
})
onBeforeUnmount(revokeCaptchaUrl)
</script>
