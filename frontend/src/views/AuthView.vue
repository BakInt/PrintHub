<template>
  <!-- 登录/注册：视口内水平垂直居中；flex-wrap 让「初始化恢复」卡片在桌面端与登录卡并排、
       手机端独占一行，恢复卡不可用时登录卡严格居中 -->
  <section
    class="flex min-h-[calc(100svh-152px-env(safe-area-inset-bottom))] flex-wrap items-center justify-center gap-6 py-4 md:min-h-[calc(100svh-108px)]"
  >
    <!-- 登录 / 注册 -->
    <Card class="w-full max-w-sm py-8 sm:max-w-md sm:px-8">
      <CardHeader class="grid gap-2">
        <CardTitle class="font-display text-2xl tracking-tight sm:text-3xl">
          {{ mode === 'login' ? '登录云打印' : '注册账号' }}
        </CardTitle>
        <CardDescription class="text-[15px]">
          {{ mode === 'login' ? '使用账号登录，管理余额与打印记录' : '注册新账号，余额充值与联系人绑定更方便' }}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form class="grid gap-4 sm:gap-5" @submit.prevent="submit">
          <div class="grid gap-2">
            <Label for="auth-username" class="text-sm font-semibold">用户名</Label>
            <Input id="auth-username" v-model="username" autocomplete="username" class="h-11 text-base md:text-base" />
          </div>
          <div v-if="mode === 'register'" class="grid gap-2">
            <Label for="auth-email" class="text-sm font-semibold">邮箱</Label>
            <Input id="auth-email" v-model="email" type="email" class="h-11 text-base md:text-base" />
          </div>
          <div class="grid gap-2">
            <Label for="auth-password" class="text-sm font-semibold">密码</Label>
            <Input id="auth-password" v-model="password" type="password" autocomplete="current-password" class="h-11 text-base md:text-base" />
          </div>
          <div class="grid gap-2">
            <Label for="auth-captcha" class="text-sm font-semibold">验证码</Label>
            <div class="flex items-center gap-2.5">
              <Input id="auth-captcha" v-model="captcha" autocomplete="off" inputmode="numeric" class="h-11 flex-1 text-base md:text-base" />
              <button
                type="button"
                class="h-11 w-[132px] shrink-0 overflow-hidden rounded-lg border bg-muted/60 transition-colors hover:border-primary/50 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="captchaLoading"
                title="点击刷新验证码"
                aria-label="点击刷新验证码"
                @click="refreshCaptcha"
              >
                <img v-if="captchaUrl" :src="captchaUrl" alt="验证码" class="h-full w-full object-cover" />
                <span v-else class="text-xs text-muted-foreground">{{ captchaLoading ? '加载中' : '刷新验证码' }}</span>
              </button>
            </div>
          </div>
          <small v-if="captchaError" class="text-[13px] text-destructive">{{ captchaError }}</small>
          <!-- 登录/注册错误提示：普通错误黄色警示；剩余 1 次或已触发锁定时升级为红色。
               文案完全来自后端（含「还可尝试 N 次」「账号已锁定，请 N 分钟后重试」），前端不做计数。 -->
          <Alert v-if="error" :class="errorKind === 'danger'
            ? 'border-destructive/30 bg-destructive/10 text-destructive'
            : 'border-warning/30 bg-warning/10 text-warning'">
            <TriangleAlert class="size-4" />
            <AlertDescription :class="errorKind === 'danger' ? 'text-destructive' : 'text-warning'">{{ error }}</AlertDescription>
          </Alert>
          <Button type="submit" class="mt-1 h-11 w-full text-base font-bold">
            <LogIn />
            {{ mode === 'login' ? '登录' : '注册' }}
          </Button>
          <Button variant="link" type="button" size="sm" class="text-[15px] text-muted-foreground" @click="toggleMode">
            {{ mode === 'login' ? '没有账号？注册' : '已有账号？登录' }}
          </Button>
        </form>
      </CardContent>
    </Card>

    <!-- 初始化恢复（仅新安装可用），与登录卡同一套尺寸规范 -->
    <Card v-if="showInitialRestore" class="w-full max-w-sm py-8 sm:max-w-md sm:px-8">
      <CardHeader class="grid gap-2">
        <CardTitle class="font-display text-2xl tracking-tight sm:text-3xl">从备份文件恢复</CardTitle>
        <CardDescription class="text-[15px]">仅新安装或无业务数据时可用</CardDescription>
      </CardHeader>
      <CardContent class="grid gap-4 sm:gap-5">
        <label
          class="flex cursor-pointer flex-col items-center justify-center gap-2.5 rounded-xl border-2 border-dashed border-border px-6 py-10 text-center text-primary transition-colors hover:border-primary hover:bg-accent/70"
          :class="restoreDragging ? 'border-solid border-primary bg-accent' : ''"
          @dragover.prevent="restoreDragging = true"
          @dragleave.prevent="restoreDragging = false"
          @drop.prevent="dropRestoreFile"
        >
          <UploadCloud class="size-8" />
          <span class="text-[15px] font-bold">拖拽备份文件到这里，或点击上传</span>
          <small class="text-[13px] text-muted-foreground">支持 .zip / .tar.gz / .tgz 备份包</small>
          <input type="file" accept=".zip,.tar.gz,.tgz" class="sr-only" @change="chooseRestoreFile" />
        </label>
        <div v-if="restoreInfo" class="grid gap-2.5 rounded-xl border border-primary/25 bg-accent/60 p-4">
          <strong class="break-all text-[15px] text-foreground">{{ restoreInfo.filename }}</strong>
          <span class="text-[13px] text-muted-foreground">
            备份时间：{{ formatDateTime(restoreInfo.backup_time) }} · 数据版本：{{ restoreInfo.data_version }}
          </span>
          <Button variant="destructive" class="h-11 text-base" :disabled="restoreBusy" @click="restoreBackup">确认恢复并刷新</Button>
        </div>
        <Alert v-if="restoreError" class="border-warning/30 bg-warning/10 text-warning">
          <TriangleAlert class="size-4" />
          <AlertDescription class="text-warning">{{ restoreError }}</AlertDescription>
        </Alert>
      </CardContent>
    </Card>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { LogIn, TriangleAlert, UploadCloud } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { buildApiUrl, request } from '@/api/client'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

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
// 错误提示等级：'warning'（黄色）为默认；后端告知「剩余 1 次」或「已锁定」时升级 'danger'（红色）。
// 只消费后端 detail 里的 remaining_attempts / locked 字段做样式分级，计数逻辑全部在后端。
const errorKind = ref('warning')
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
  resetError()
  refreshCaptcha()
}

function resetError() {
  error.value = ''
  errorKind.value = 'warning'
}

async function submit() {
  try {
    if (mode.value === 'login') await auth.login(username.value, password.value, captcha.value)
    else await auth.register(username.value, password.value, email.value, captcha.value)
    router.push('/')
  } catch (err) {
    error.value = err.message
    const detail = err?.data?.detail
    const remaining = Number(detail?.remaining_attempts)
    errorKind.value = Boolean(detail?.locked) || remaining === 1 ? 'danger' : 'warning'
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
