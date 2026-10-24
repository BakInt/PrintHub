<template>
  <section class="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(320px,380px)] lg:items-start lg:gap-6 max-md:pb-[calc(64px+env(safe-area-inset-bottom))]">
    <!-- 促销横幅 -->
    <div v-if="promotionNotices.length" class="grid gap-2.5 lg:col-span-full lg:gap-2.5">
      <Alert
        v-for="notice in promotionNotices"
        :key="notice.title"
        class="border-primary/20 bg-accent text-accent-foreground"
      >
        <Megaphone class="size-4" />
        <AlertTitle>{{ notice.title }}</AlertTitle>
        <AlertDescription class="text-accent-foreground/90">{{ notice.message }}</AlertDescription>
      </Alert>
    </div>

    <!-- 上传主卡片 -->
    <Card class="min-h-full py-5">
      <CardHeader class="flex flex-row items-start justify-between gap-4">
        <div class="grid max-w-3xl gap-2">
          <p class="text-[13px] font-bold tracking-widest text-primary">在线自助打印</p>
          <CardTitle class="font-display text-2xl leading-tight tracking-tight sm:text-3xl">
            上传文件，在线打印
          </CardTitle>
          <CardDescription class="max-md:text-sm">
            支持 PDF、Office 文档与常见图片，自动转换与计价，安全检测通过后在线支付，打印任务自动下发。
          </CardDescription>
        </div>
        <Printer class="hidden size-8 text-primary opacity-90 sm:block" aria-hidden="true" />
      </CardHeader>

      <CardContent class="grid gap-4">
        <!-- 未登录提示 -->
        <div
          v-if="!auth.user"
          class="grid gap-3 rounded-xl border border-primary/25 bg-accent/60 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4"
        >
          <div class="grid min-w-0 gap-1">
            <strong class="text-[15px] text-foreground">未登录也能打印</strong>
            <span class="text-sm leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
              先上传文件并填写联系人即可创建支付订单，登录后可管理余额和历史记录。
            </span>
          </div>
          <Button as-child variant="secondary" class="h-10 w-full shrink-0 sm:w-auto">
            <RouterLink to="/login">登录 / 注册</RouterLink>
          </Button>
        </div>

        <!-- 拖拽上传区：手机端为品牌渐变主视觉，桌面端为虚线框 -->
        <label
          class="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-border px-6 py-10 text-center text-primary transition-colors hover:border-primary hover:bg-accent/70 focus-within:ring-2 focus-within:ring-ring/40 max-sm:border-transparent max-sm:bg-linear-to-br max-sm:from-primary max-sm:to-(--brand-deep) max-sm:text-primary-foreground max-sm:shadow-lg max-sm:shadow-primary/30 max-sm:hover:border-transparent max-sm:hover:bg-linear-to-br"
          :class="dragging ? 'border-solid border-primary bg-accent max-sm:from-(--brand-deep) max-sm:to-primary' : ''"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="handleDrop"
        >
          <UploadCloud class="size-9" />
          <span class="text-base font-bold sm:text-lg">拖拽文件到这里，或点击选择</span>
          <small class="max-w-xs text-[13px] leading-relaxed max-sm:text-primary-foreground/85 sm:text-muted-foreground">
            支持 PDF、Office 文档和常见图片，{{ uploadLimitText }}
          </small>
          <input type="file" multiple class="sr-only" @change="handleSelect" />
        </label>

        <!-- 操作反馈 -->
        <Alert v-if="message" :class="noticeClass">
          <TriangleAlert v-if="noticeType === 'warning'" class="size-4" />
          <CircleCheck v-else-if="noticeType === 'success'" class="size-4" />
          <Info v-else class="size-4" />
          <AlertDescription class="whitespace-pre-line">{{ message }}</AlertDescription>
        </Alert>

        <!-- 三步引导（桌面端展示） -->
        <div v-if="!files.length" class="hidden gap-3 md:grid md:grid-cols-3">
          <div v-for="step in stepCards" :key="step.title" class="grid content-start gap-2.5 rounded-lg border border-border/70 bg-muted/60 p-4">
            <span class="grid size-7 place-items-center rounded-lg bg-accent text-[13px] font-extrabold text-accent-foreground">
              {{ step.no }}
            </span>
            <strong class="text-[15px] text-foreground">{{ step.title }}</strong>
            <p class="text-[13px] leading-relaxed text-muted-foreground">{{ step.desc }}</p>
          </div>
        </div>

        <!-- 文件列表 -->
        <div class="grid gap-2.5">
          <div
            v-for="file in files"
            :key="file.file_id"
            class="grid items-start gap-3 rounded-xl border bg-card p-3.5 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
            :class="file.safe ? 'border-border' : 'border-destructive/40 bg-destructive/5'"
          >
            <FileText class="hidden size-[22px] text-primary sm:block" aria-hidden="true" />
            <div class="grid min-w-0 gap-1.5">
              <strong class="break-all text-sm font-semibold leading-snug text-foreground">{{ file.file_name }}</strong>
              <span class="text-[13px] text-muted-foreground">
                {{ file.page_count }} 页 · {{ file.file_size }} MB · 黑色覆盖率 {{ file.black_coverage }}%
              </span>
              <div class="flex flex-wrap gap-2">
                <Badge :variant="file.converted ? 'default' : 'secondary'" class="max-md:h-6">
                  {{ file.converted ? '已转换为 PDF' : '原始 PDF' }}
                </Badge>
                <Badge v-if="file.safe" variant="outline" class="max-md:h-6">点击小眼睛预览 PDF</Badge>
              </div>
            </div>
            <div class="flex items-center gap-2 max-sm:justify-end">
              <Button variant="outline" size="icon-sm" class="max-md:size-9" title="预览" :disabled="!file.safe" @click="openPreview(file)">
                <Eye />
              </Button>
              <Button variant="destructive" size="icon-sm" class="max-md:size-9" title="移除" @click="removeFile(file.file_id)">
                <Trash2 />
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 打印设置侧栏 -->
    <Card class="gap-4 py-5 lg:sticky lg:top-20">
      <CardHeader class="pb-0">
        <CardTitle class="font-display text-xl">打印设置</CardTitle>
      </CardHeader>
      <CardContent class="grid gap-3">
        <!-- 已登录：显示绑定的联系人 -->
        <div v-if="auth.user" class="grid gap-2.5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-bold text-foreground">打印联系人</span>
            <Button as-child variant="ghost" size="sm" class="h-8 text-primary hover:text-primary">
              <RouterLink to="/user/dashboard">修改</RouterLink>
            </Button>
          </div>
          <div v-if="profileContactComplete" class="grid gap-1 rounded-lg border border-primary/25 bg-accent px-3.5 py-2.5">
            <strong class="break-all text-sm text-foreground">{{ contactName }}</strong>
            <span class="break-all text-sm text-muted-foreground">{{ contactPhone }}</span>
          </div>
          <Alert v-else class="border-warning/30 bg-warning/10 text-warning">
            <TriangleAlert class="size-4" />
            <AlertDescription class="text-warning">
              请先在个人中心绑定姓名和手机号，系统会自动填写打印联系人。
            </AlertDescription>
          </Alert>
        </div>

        <!-- 未登录：填写联系人 -->
        <template v-else>
          <div class="grid gap-1.5">
            <Label for="guest-name" class="text-sm font-bold">打印人姓名</Label>
            <Input id="guest-name" v-model.trim="guestContactName" maxlength="40" placeholder="请输入打印人姓名" class="h-10" />
          </div>
          <div class="grid gap-1.5">
            <Label for="guest-phone" class="text-sm font-bold">联系电话</Label>
            <Input
              id="guest-phone"
              v-model="guestContactPhone"
              type="tel"
              inputmode="numeric"
              maxlength="11"
              placeholder="请输入 11 位手机号"
              class="h-10"
              @input="sanitizeContactPhone"
            />
            <small v-if="guestContactPhone && !contactPhoneValid" class="text-xs text-destructive">
              请输入 11 位中国大陆手机号
            </small>
          </div>
        </template>

        <!-- 【新功能】合并双面打印：勾选后全部文档按上传顺序合并为一个双面打印流，
             不同文档的页面连续排到纸张正反面（两份单页文档可打在同一张纸正反面）。
             打印机未开启「支持自动双面打印」时这里完全隐藏。 -->
        <label
          v-if="safeFiles.length && autoDuplexSupported"
          class="flex cursor-pointer items-center gap-2.5 rounded-xl border bg-muted/50 p-3.5"
          :class="{ 'cursor-not-allowed opacity-60': !mergeDuplexAvailable }"
        >
          <Checkbox
            :model-value="mergeDuplex"
            :disabled="!mergeDuplexAvailable"
            @update:model-value="(checked) => (mergeDuplex = !!checked)"
          />
          <span class="text-sm font-bold text-foreground">合并双面</span>
        </label>

        <!-- 【新增功能】彩色打印：仅当后台把当前打印机配置为「支持彩色打印」时展示 -->
        <div v-if="colorSupported" class="grid gap-2.5 rounded-xl border bg-muted/50 p-3.5">
          <span class="text-sm font-bold text-foreground">彩色打印</span>
          <Tabs :model-value="useColor ? 'color' : 'bw'" @update:model-value="(value) => (useColor = value === 'color')">
            <TabsList class="h-10! w-full!">
              <TabsTrigger value="bw" class="flex-1" title="按原有黑白流程处理并打印">黑白</TabsTrigger>
              <TabsTrigger value="color" class="flex-1" title="保留文件原始色彩直接送给打印机，不做黑白转换">彩色</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <div class="grid gap-1.5">
          <Label for="copies" class="text-sm font-bold">份数</Label>
          <Input id="copies" v-model.number="copies" type="number" min="1" max="99" class="h-10" />
        </div>

        <div class="grid gap-1.5">
          <Label class="text-sm font-bold">支付方式</Label>
          <Tabs :model-value="paymentMethod" @update:model-value="(value) => (paymentMethod = value)">
            <TabsList class="h-10! w-full!">
              <TabsTrigger value="wxpay" class="flex-1">微信</TabsTrigger>
              <TabsTrigger value="alipay" class="flex-1">支付宝</TabsTrigger>
              <TabsTrigger value="balance" :disabled="!auth.user" class="flex-1">余额</TabsTrigger>
            </TabsList>
          </Tabs>
          <small v-if="!auth.user" class="text-xs leading-relaxed text-muted-foreground">
            余额支付仅对已登录用户开放，当前可直接使用微信或支付宝下单。
          </small>
        </div>

        <!-- 预计金额 -->
        <div class="flex items-center justify-between gap-3 rounded-xl border border-primary/25 bg-accent/70 p-4">
          <div class="grid min-w-0 gap-1">
            <span class="text-sm font-semibold text-foreground">预计金额</span>
            <small v-if="estimateDetail.discount_amount > 0" class="text-xs leading-snug text-muted-foreground [overflow-wrap:anywhere]">
              原价 ¥{{ Number(estimateDetail.base_amount || 0).toFixed(2) }} · 已优惠 ¥{{ Number(estimateDetail.discount_amount || 0).toFixed(2) }}
            </small>
            <small v-if="estimateDetail.applied_discount" class="text-xs leading-snug text-muted-foreground [overflow-wrap:anywhere]">
              {{ estimateDetail.applied_discount.label }} · {{ estimateDetail.sheet_count || 0 }} 张
            </small>
          </div>
          <strong class="font-display text-2xl font-bold tracking-tight text-primary tabular-nums max-sm:text-xl">
            ¥{{ estimatedAmount.toFixed(2) }}
          </strong>
        </div>

        <Button size="lg" class="h-11 w-full font-bold max-md:hidden" :disabled="!canSubmit || submitting" @click="createOrder">
          <CreditCard />
          {{ submitting ? '提交中...' : paymentMethod === 'balance' ? '余额支付并打印' : '创建支付订单' }}
        </Button>
      </CardContent>
    </Card>

    <!-- 手机端固定底部提交栏（叠在底部 Tab 栏之上） -->
    <div
      class="fixed inset-x-2 bottom-[calc(72px+env(safe-area-inset-bottom))] z-30 flex items-center gap-3 rounded-xl border border-primary/25 bg-card/95 p-2.5 shadow-lg shadow-black/10 backdrop-blur md:hidden"
    >
      <div class="grid min-w-0 flex-1 gap-0.5">
        <span class="text-xs text-muted-foreground">预计金额</span>
        <strong class="font-display text-xl leading-none font-bold text-primary tabular-nums">
          ¥{{ estimatedAmount.toFixed(2) }}
        </strong>
        <small v-if="estimateDetail.discount_amount > 0" class="truncate text-xs text-muted-foreground">
          已优惠 ¥{{ Number(estimateDetail.discount_amount || 0).toFixed(2) }}
        </small>
      </div>
      <Button class="h-11 min-w-28 flex-1 font-bold sm:flex-none" :disabled="!canSubmit || submitting" @click="createOrder">
        <CreditCard />
        {{ submitting ? '提交中...' : paymentMethod === 'balance' ? '余额支付' : '去支付' }}
      </Button>
    </div>

    <!-- PDF 预览弹窗：点文件行的眼睛图标后以 Dialog 居中弹出，不再在页面底部展开 -->
    <Dialog
      :open="previewOpen"
      @update:open="(open) => { previewOpen = open; if (!open) previewFile = null }"
    >
      <DialogScrollContent class="max-w-[calc(100vw-2rem)] gap-3 p-4 sm:max-w-3xl sm:p-5">
        <DialogHeader class="gap-1">
          <DialogTitle class="pr-6 font-display text-lg leading-snug break-all">
            {{ previewFile?.file_name || 'PDF 预览' }}
          </DialogTitle>
          <DialogDescription class="max-md:text-sm">浏览器内预览 PDF（非 PDF 文件已自动转换）</DialogDescription>
        </DialogHeader>
        <iframe
          v-if="previewFile"
          :src="previewFile.preview_url"
          :title="previewFile.file_name || 'PDF 预览'"
          class="h-[70vh] min-h-80 w-full rounded-lg border bg-card"
        ></iframe>
      </DialogScrollContent>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { CircleCheck, CreditCard, Eye, FileText, Info, Megaphone, Printer, Trash2, TriangleAlert, UploadCloud } from 'lucide-vue-next'
import { buildApiUrl, request } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { formatOrderCreatedQueueMessage } from '@/utils/queue'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogDescription, DialogHeader, DialogScrollContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const router = useRouter()
const auth = useAuthStore()
const files = ref([])
// PDF 预览改为弹窗：previewOpen 控制显隐，previewFile 保存当前预览的文件（关闭即清空、卸载 iframe）
const previewOpen = ref(false)
const previewFile = ref(null)
const guestContactName = ref('')
const guestContactPhone = ref('')
const copies = ref(1)
const mergeDuplex = ref(false)
const paymentMethod = ref('wxpay')
const estimatedAmount = ref(0)
const estimateDetail = ref({})
const promotions = ref(null)
const uploadLimits = ref(null)
// 【新增功能】printOptions 来自公开接口 /api/print-options（当前打印机的彩色/自动双面能力）；
// useColor 是用户的彩色选择，只有打印机支持彩色时才会提交给后端。
const printOptions = ref(null)
const useColor = ref(false)
const dragging = ref(false)
const submitting = ref(false)
const message = ref('')
const noticeType = ref('')

// 首页三步引导文案（桌面端展示）
const stepCards = [
  { no: '1', title: '上传打印文件', desc: '系统会自动完成格式转换、页数统计和安全检测。' },
  { no: '2', title: '填写打印信息', desc: '设置份数、单双面和联系人，右侧会实时计算预计金额。' },
  { no: '3', title: '支付后进入打印流程', desc: '支持微信、支付宝支付；登录用户还可以使用余额直接支付。' }
]

// 提示条样式：按语义状态色（--success/--warning/--primary）组合，跟随亮暗主题
const noticeClass = computed(() => {
  if (noticeType.value === 'warning') return 'border-warning/30 bg-warning/10 text-warning'
  if (noticeType.value === 'success') return 'border-success/30 bg-success/10 text-success'
  return 'border-primary/25 bg-accent text-accent-foreground'
})

const safeFiles = computed(() => files.value.filter((file) => file.safe))
// 【新增功能】打印机能力完全由后台「打印机管理」的配置驱动，前端不硬编码：
// 只有 printer_configured 且 is_support_color/is_support_auto_duplex 为 true 时才展示对应选项
// （后端在未配置默认打印机时会把两项能力归零，这里同时校验以保证口径一致）。
const colorSupported = computed(
  () => printOptions.value?.printer_configured === true && printOptions.value?.is_support_color === true,
)
const autoDuplexSupported = computed(
  () => printOptions.value?.printer_configured === true && printOptions.value?.is_support_auto_duplex === true,
)
// 【新功能】合并双面打印：勾选后全部文档按上传顺序合并为一个双面打印流，
// 不同文档的页面连续排到纸张正反面（两份单页文档可打在同一张纸正反面）。
const totalPages = computed(() => safeFiles.value.reduce((sum, file) => sum + (Number(file.page_count) || 0), 0))
const mergeDuplexAvailable = computed(() => safeFiles.value.length > 0 && totalPages.value >= 2)
watch(mergeDuplexAvailable, (available) => {
  if (!available) mergeDuplex.value = false
})
// 页面打开时首屏接口失败（如后端重启窗口期）后，用户上传文件时补拉一次仍缺失的数据，
// 避免双面/彩色选项与上传限制提示因一次瞬时失败就整个会话消失。
watch(safeFiles, (list) => {
  if (!list.length) return
  if (!printOptions.value) loadPrintOptions()
  if (!uploadLimits.value) loadLimits()
})
const contactName = computed(() => (auth.user ? auth.user.real_name || '' : guestContactName.value).trim())
const contactPhone = computed(() => auth.user ? auth.user.phone || '' : guestContactPhone.value)
const profileContactComplete = computed(() => Boolean(auth.user?.real_name && /^1[3-9]\d{9}$/.test(auth.user?.phone || '')))
const contactNameValid = computed(() => contactName.value.trim().length > 0 && contactName.value.trim().length <= 40)
const contactPhoneValid = computed(() => /^1[3-9]\d{9}$/.test(contactPhone.value))
const copiesValid = computed(() => Number(copies.value) >= 1 && Number(copies.value) <= 99)
const canSubmit = computed(() => safeFiles.value.length > 0 && copiesValid.value && contactNameValid.value && contactPhoneValid.value)
const discountText = (discount) => {
  const value = Number(discount)
  if (!Number.isFinite(value) || value <= 0) return ''
  const percent = value <= 1 ? value * 100 : value
  const fold = percent / 10
  return `${Number.isInteger(fold) ? fold : fold.toFixed(1)}折`
}
const promotionNotices = computed(() => {
  if (!promotions.value) return []
  const notices = []
  const dailyOffer = promotions.value?.daily_limited_offer
  if (dailyOffer?.enabled) {
    const offerText = dailyOffer.free ? '免费打印' : `享 ${discountText(dailyOffer.discount)}`
    const timeText = dailyOffer.all_day ? '今天全天' : `今天 ${dailyOffer.start_time}-${dailyOffer.end_time}`
    notices.push({
      title: dailyOffer.free ? (dailyOffer.all_day ? '今日全天免费' : '今日限时免费') : (dailyOffer.all_day ? '今日全天福利' : '今日限时福利'),
      message: `${timeText}下单${offerText}，限量 ${dailyOffer.quota} 张/份，当前还剩 ${dailyOffer.remaining_sheets} 张/份`
    })
  }
  const rules = promotions.value?.bulk_discount?.rules || []
  if (promotions.value?.bulk_discount?.enabled && rules.length) {
    notices.push({
      title: '多印多省',
      message: rules.map((rule) => `一次打印满 ${rule.min_sheets} 张/份享 ${discountText(rule.discount)}`).join('，')
    })
  }
  return notices
})

// 首页文案直接使用后端真实校验所用的上传限制，避免与后台「系统设置」不一致。
const uploadLimitText = computed(() => {
  const limits = uploadLimits.value
  if (!limits) return '单文件大小与页数上限以系统设置为准'
  const parts = []
  const sizeMb = Number(limits.max_file_size_mb)
  if (Number.isFinite(sizeMb) && sizeMb > 0) parts.push(`单文件不超过 ${sizeMb}MB`)
  const pages = Number(limits.max_pages)
  if (Number.isFinite(pages) && pages > 0) parts.push(`最多 ${pages} 页`)
  return parts.length ? parts.join('，') : '单文件大小与页数上限以系统设置为准'
})

onMounted(() => {
  loadPromotions()
  loadLimits()
  loadPrintOptions()
})

watch(() => auth.user, (user) => {
  if (!user && paymentMethod.value === 'balance') paymentMethod.value = 'wxpay'
})

watch([safeFiles, copies, mergeDuplex, printOptions], async () => {
  const fileIds = safeFiles.value.map((file) => file.file_id)
  if (!fileIds.length) {
    estimatedAmount.value = 0
    estimateDetail.value = {}
    return
  }
  const data = await request('/api/price', {
    method: 'POST',
    body: { file_ids: fileIds, copies: copies.value, merge_duplex: autoDuplexSupported.value && mergeDuplex.value },
  })
  estimatedAmount.value = data.amount
  estimateDetail.value = data
}, { deep: true })

// 首屏 GET（促销/上传限制/打印机能力）在页面打开瞬间若恰逢后端重启或网络抖动会失败，
// 且一旦失败整个会话都不再重试，导致双面/彩色选项、上传限制提示静默消失——
// 这里做有限重试（间隔 800ms），上传文件时还会对仍缺失的数据兜底补拉一次。
async function fetchWithRetry(path, retries = 2) {
  let lastError
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await request(path)
    } catch (error) {
      lastError = error
      if (attempt < retries) await new Promise((resolve) => setTimeout(resolve, 800))
    }
  }
  throw lastError
}

async function loadPromotions() {
  try {
    promotions.value = await fetchWithRetry('/api/promotions')
  } catch {
    promotions.value = null
  }
}

async function loadLimits() {
  try {
    uploadLimits.value = await fetchWithRetry('/api/limits')
  } catch {
    uploadLimits.value = null
  }
}

// 【新增功能】读取当前（默认）打印机的彩色/自动双面能力，用于条件渲染「彩色打印」「合并双面」勾选。
async function loadPrintOptions() {
  try {
    const data = await fetchWithRetry('/api/print-options')
    printOptions.value = data
    // 打印机不支持彩色时强制回到黑白，避免请求里带上不支持的能力。
    if (data?.is_support_color !== true) useColor.value = false
  } catch {
    printOptions.value = null
    useColor.value = false
  }
}

function setNotice(text, type = '') {
  message.value = text
  noticeType.value = type
}

function sanitizeContactPhone(event) {
  guestContactPhone.value = event.target.value.replace(/\D/g, '').slice(0, 11)
}

async function uploadOne(file) {
  const form = new FormData()
  form.append('file', file)
  const result = await request('/api/upload', { method: 'POST', body: form })
  files.value.push(result.data)
  setNotice(result.data.converted ? '文件已转换为 PDF，点击小眼睛可在浏览器内预览。' : 'PDF 文件已处理完成，点击小眼睛可在浏览器内预览。', 'success')
  if (!result.data.safe) setNotice(result.data.warning_message || '文件未通过安全检测', 'warning')
}

async function uploadFiles(fileList) {
  setNotice('正在上传并检测文件...')
  for (const file of Array.from(fileList)) {
    try {
      await uploadOne(file)
    } catch (error) {
      setNotice(error.message, 'warning')
    }
  }
  if (!message.value || noticeType.value !== 'warning') setNotice('文件处理完成，非 PDF 文件已转换为 PDF。', 'success')
}

function handleSelect(event) {
  uploadFiles(event.target.files)
  event.target.value = ''
}

function handleDrop(event) {
  dragging.value = false
  uploadFiles(event.dataTransfer.files)
}

function removeFile(fileId) {
  files.value = files.value.filter((file) => file.file_id !== fileId)
  if (previewFile.value?.file_id === fileId) {
    previewFile.value = null
    previewOpen.value = false
  }
}

function openPreview(file) {
  if (!file.safe) return
  previewFile.value = file
  previewOpen.value = true
}

async function submitPrintOrder(method) {
  const printSettings = {
    copies: copies.value,
    contact_name: contactName.value.trim(),
    contact_phone: contactPhone.value
  }
  // 【新增功能】只在打印机确实支持对应能力时才携带新参数：
  // use_color 决定后端是否跳过黑白化处理（true=原样送印）；
  // merge_duplex=true 时后端把全部文档按上传顺序合并为一个双面任务下发。
  if (colorSupported.value) printSettings.use_color = useColor.value
  if (autoDuplexSupported.value) printSettings.merge_duplex = mergeDuplex.value
  return request('/api/payment/create', {
    method: 'POST',
    body: {
      file_ids: safeFiles.value.map((file) => file.file_id),
      print_settings: printSettings,
      payment_method: method
    }
  })
}

function validateOrderForm() {
  if (!safeFiles.value.length) {
    setNotice('请先上传并选择通过安全检测的文件。', 'warning')
    return false
  }
  if (!contactNameValid.value) {
    setNotice(auth.user ? '请先在个人中心绑定姓名。' : '请填写打印人姓名。', 'warning')
    return false
  }
  if (!contactPhoneValid.value) {
    setNotice(auth.user ? '请先在个人中心绑定 11 位中国大陆手机号。' : '请输入 11 位中国大陆手机号。', 'warning')
    return false
  }
  if (!copiesValid.value) {
    setNotice('打印份数需在 1 到 99 之间。', 'warning')
    return false
  }
  return true
}

function shouldRetryLegacyEpay(error) {
  return paymentMethod.value !== 'balance' && /payment_method|\^\(epay\|balance\)\$/.test(error.message)
}

function handleCreatedOrder(data, method) {
  if (data.qr_code_url && method !== 'balance') {
    window.location.href = buildApiUrl(data.qr_code_url)
    return
  }
  const queueMessage = formatOrderCreatedQueueMessage(data.queue)
  if (queueMessage) setNotice(queueMessage, 'success')
  router.push(`/payment/${data.order_id}`)
}

async function createOrder() {
  if (!validateOrderForm()) return
  submitting.value = true
  try {
    const data = await submitPrintOrder(paymentMethod.value)
    handleCreatedOrder(data, paymentMethod.value)
  } catch (error) {
    if (shouldRetryLegacyEpay(error)) {
      try {
        const data = await submitPrintOrder('epay')
        handleCreatedOrder(data, 'epay')
        return
      } catch (retryError) {
        setNotice(retryError.message, 'warning')
        return
      }
    }
    setNotice(error.message, 'warning')
  } finally {
    submitting.value = false
  }
}
</script>
