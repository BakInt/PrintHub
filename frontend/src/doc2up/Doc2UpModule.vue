<script setup>
// 两页合一打印模块页（/cert/doc-2up）：上传文档 → 复用主程序上传管线转 PDF（含安全检测）
// → 每两页旋转 90° 缩排到一页 A4（竖向文档转横向、横向文档转竖向）→ 预览 → 下单
//（余额支付，支持勾选双面打印）。复用 cert 模块的 CertOrderPanel 下单面板。
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { ArrowLeft, CircleAlert, FileStack, LoaderCircle, LogIn, RotateCcw } from 'lucide-vue-next'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import CertOrderPanel from '@/cert/components/CertOrderPanel.vue'
import { fetchCertTemplates } from '@/cert/api'
import { useAuthStore } from '@/stores/auth'
import { createDoc2Up, uploadDocument } from './api'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const fileInput = ref(null)
const uploading = ref(false)
const transforming = ref(false)
// 源文件（/api/upload 返回）：{ file_id, file_name, page_count, safe, warning_message }
const source = ref(null)
// 合成结果：{ file_id, page_count, preview_url }
const result = ref(null)

const loginRedirect = computed(() => ({ path: '/login', query: { redirect: route.fullPath } }))

// 模板启停感知：doc2up 在 cert_templates 有登记行（见 cert/templates_seed.py），
// 后台「证件照管理」停用后门户卡片消失，深链进入本页显示「已下架」（与 cert 模块页一致）。
const templatesLoading = ref(true)
const templatesError = ref(false)
const templateAvailable = ref(false)

async function loadTemplate() {
  templatesLoading.value = true
  templatesError.value = false
  try {
    const list = await fetchCertTemplates()
    templateAvailable.value = list.some((item) => item.code === 'doc2up')
  } catch {
    templatesError.value = true
  } finally {
    templatesLoading.value = false
  }
}

onMounted(loadTemplate)

const ACCEPT_TYPES = '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg'

function requireLogin() {
  if (auth.user) return true
  router.push(loginRedirect.value)
  return false
}

async function pick(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!requireLogin()) return
  uploading.value = true
  result.value = null
  source.value = null
  try {
    const response = await uploadDocument(file)
    const data = response?.data || response
    if (!data?.safe) {
      toast.error(data?.warning_message || '文件未通过安全检测，无法打印')
      return
    }
    source.value = data
    if (data.formula_warning || data.font_warning || data.missing_fonts_warning) {
      const first = data.formula_warning || data.font_warning || data.missing_fonts_warning
      toast.warning(String(first).split('。')[0] + '。')
    }
  } catch (error) {
    toast.error(error?.message || '上传失败，请稍后重试')
  } finally {
    uploading.value = false
  }
}

async function transform() {
  if (!source.value) return
  transforming.value = true
  try {
    result.value = await createDoc2Up(source.value.file_id)
    toast.success('合成成功，请预览并确认打印')
  } catch (error) {
    toast.error(error?.message || '合成失败，请稍后重试')
  } finally {
    transforming.value = false
  }
}

function reset() {
  source.value = null
  result.value = null
}
</script>

<template>
  <div class="mx-auto w-full max-w-5xl px-3 py-6 sm:px-6">
    <!-- 页头 -->
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h1 class="font-display text-2xl font-bold tracking-tight sm:text-3xl">两页合一打印</h1>
        <p class="mt-1 text-sm text-muted-foreground">每两页文档缩排到一页 A4，自动旋转方向，省纸清晰</p>
      </div>
      <Button as-child variant="ghost" size="sm" class="h-9 text-muted-foreground">
        <RouterLink to="/cert"><ArrowLeft class="size-4" aria-hidden="true" />返回功能门户</RouterLink>
      </Button>
    </div>

    <Alert v-if="!auth.user" class="mb-4">
      <LogIn class="size-4" aria-hidden="true" />
      <AlertTitle>未登录</AlertTitle>
      <AlertDescription class="flex flex-wrap items-center gap-2">
        <span>可以先浏览；上传与打印需要登录（使用余额支付）。</span>
        <Button as-child size="sm" variant="outline" class="h-8">
          <RouterLink :to="loginRedirect">去登录</RouterLink>
        </Button>
      </AlertDescription>
    </Alert>

    <!-- 模板加载 / 下架状态 -->
    <div v-if="templatesLoading" class="mb-4 grid gap-3 sm:grid-cols-2">
      <Skeleton class="h-40 rounded-xl" />
      <Skeleton class="h-40 rounded-xl" />
    </div>
    <Alert v-else-if="templatesError" variant="destructive" class="mb-4">
      <CircleAlert class="size-4" aria-hidden="true" />
      <AlertTitle>功能信息加载失败</AlertTitle>
      <AlertDescription>
        <Button size="sm" variant="outline" class="mt-2 h-8" @click="loadTemplate">重试</Button>
      </AlertDescription>
    </Alert>
    <Alert v-else-if="!templateAvailable" variant="destructive" class="mb-4">
      <CircleAlert class="size-4" aria-hidden="true" />
      <AlertTitle>该功能已下架</AlertTitle>
      <AlertDescription>
        <Button as-child size="sm" variant="outline" class="mt-2 h-8">
          <RouterLink to="/cert">返回功能门户</RouterLink>
        </Button>
      </AlertDescription>
    </Alert>

    <template v-else>
      <Alert class="mb-4">
        <AlertDescription>
          上传文档（PDF / Office / 图片）自动转换成 PDF 后，每两页旋转 90° 缩排到一页 A4：
          竖向文档转成横向上下排布，横向文档转成竖向左右排布；支持勾选双面打印（打印机支持时）。
        </AlertDescription>
      </Alert>

      <!-- 上传 / 源文件 -->
      <div
        v-if="!source"
        class="grid h-40 place-items-center rounded-xl border border-dashed bg-card/50 text-muted-foreground"
      >
        <div class="flex flex-col items-center gap-2">
          <FileStack class="size-6" aria-hidden="true" />
          <p class="text-sm">上传要合并打印的文档</p>
          <Button class="h-10" :disabled="uploading" @click="requireLogin() && fileInput?.click()">
            <LoaderCircle v-if="uploading" class="size-4 animate-spin" aria-hidden="true" />
            {{ uploading ? '正在上传转换…' : '选择文件' }}
          </Button>
        </div>
      </div>

      <Card v-else>
        <CardContent class="flex flex-col gap-3 p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <span class="truncate text-sm font-semibold">{{ source.file_name }}</span>
              <Badge variant="secondary">已转换 PDF</Badge>
              <Badge variant="outline" class="text-muted-foreground">{{ source.page_count }} 页</Badge>
            </div>
            <Button variant="outline" size="sm" class="h-9" :disabled="uploading || transforming" @click="reset">
              <RotateCcw class="size-4" aria-hidden="true" />重新上传
            </Button>
          </div>
          <Button class="h-11 w-full max-w-xs text-base font-semibold" :disabled="transforming" @click="transform">
            <LoaderCircle v-if="transforming" class="size-4 animate-spin" aria-hidden="true" />
            {{ transforming ? '正在合成…' : '合成两页合一打印件' }}
          </Button>
          <p class="text-xs text-muted-foreground">
            预计输出 {{ Math.ceil(Number(source.page_count || 1) / 2) }} 页 A4（奇数页时最后一页单独占半版）。
          </p>
        </CardContent>
      </Card>

      <input ref="fileInput" type="file" :accept="ACCEPT_TYPES" class="hidden" @change="pick" />

      <!-- 合成结果：预览 + 下单 -->
      <div v-if="result" class="mt-8 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle class="text-base">打印件预览</CardTitle>
            <CardDescription>每页 A4 含两页文档内容（已按方向旋转），浅灰线为对半裁切参考。</CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-3">
            <iframe :src="result.preview_url" title="两页合一打印件预览" class="h-[60vh] w-full rounded-lg border bg-muted/30" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle class="text-base">确认打印</CardTitle>
            <CardDescription>使用账户余额支付，扣费成功后自动派发打印。</CardDescription>
          </CardHeader>
          <CardContent>
            <CertOrderPanel :file-id="result.file_id" product-name="两页合一打印" support-duplex />
          </CardContent>
        </Card>
      </div>
    </template>
  </div>
</template>
