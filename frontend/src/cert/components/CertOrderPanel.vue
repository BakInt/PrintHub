<script setup>
// 下单面板（cert 与 doc2up 模块共用）：份数 / 彩色（打印机支持时）/ 双面（模块声明
// supportDuplex 且打印机支持自动双面时展示）/ 联系人 / 价格试算 / 余额 / 知情确认 / 确认打印。
// 下单完全复用主程序接口：/api/price 试算 + /api/payment/create（balance）；
// 双面勾选映射到 print_settings.merge_duplex（单文件订单即「本文件双面打印」，
// 与首页合并双面同一语义：按 ceil(页数/2) 张 × 双面价）。
// 证照模块使用时传 template（模板价展示 + 知情确认声明）；文档类模块（两页合一）
// 不传 template、传 product-name，知情确认区自动隐藏（非证件场景无该合规要求）。
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { CircleAlert, Wallet } from 'lucide-vue-next'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuthStore } from '@/stores/auth'
import { CERT_CONSENT_TEXT } from '../constants'
import { createPayment, fetchPrice, fetchPrintOptions } from '../api'

const props = defineProps({
  fileId: { type: String, required: true },
  template: { type: Object, default: null },
  defaults: { type: Object, default: () => ({}) },
  supportDuplex: { type: Boolean, default: false },
  productName: { type: String, default: '' },
})

const router = useRouter()
const auth = useAuthStore()

const copies = ref(Number(props.defaults.copies) || 1)
const useColor = ref(false)
const duplex = ref(false)
const contactName = ref('')
const contactPhone = ref('')
const consent = ref(false)
const priceDetail = ref(null)
const priceLoading = ref(false)
const submitting = ref(false)
const balanceShortage = ref(false)
const printOptions = ref(null)

const isCertMode = computed(() => Boolean(props.template))

const colorSupported = computed(
  () => Boolean(printOptions.value?.printer_configured && printOptions.value?.is_support_color),
)

// 双面：模块声明支持 + 打印机支持自动双面 + 合计页数 ≥ 2（1 页无双面意义）。
const duplexAvailable = computed(
  () =>
    props.supportDuplex &&
    Boolean(printOptions.value?.printer_configured && printOptions.value?.is_support_auto_duplex),
)
const totalPages = computed(() => Number(priceDetail.value?.total_pages ?? 0))
const canDuplex = computed(() => duplexAvailable.value && totalPages.value >= 2)
watch(canDuplex, (available) => {
  if (!available) duplex.value = false
})

const displayName = computed(() => props.productName || props.template?.name || '打印件')

const templatePriceText = computed(() => {
  if (!props.template) return '按页计价'
  return props.template.price_mode === 'template' ? `¥${Number(props.template.price).toFixed(2)}/页` : '按页计价'
})

async function refreshPrice() {
  if (!props.fileId) return
  priceLoading.value = true
  try {
    const payload = { file_ids: [props.fileId], copies: copies.value }
    if (duplexAvailable.value) payload.merge_duplex = duplex.value
    priceDetail.value = await fetchPrice(payload)
  } catch {
    priceDetail.value = null
  } finally {
    priceLoading.value = false
  }
}

watch(copies, refreshPrice)
watch(duplex, refreshPrice)
watch(
  () => props.fileId,
  () => {
    balanceShortage.value = false
    refreshPrice()
  },
)

onMounted(async () => {
  if (auth.user) {
    contactName.value = auth.user.real_name || ''
    contactPhone.value = auth.user.phone || ''
  }
  try {
    printOptions.value = await fetchPrintOptions()
  } catch {
    printOptions.value = null
  }
  refreshPrice()
})

const amountText = computed(() =>
  priceDetail.value ? `¥${Number(priceDetail.value.amount).toFixed(2)}` : priceLoading.value ? '计算中…' : '—',
)

async function confirmPrint() {
  if (!auth.user) {
    router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
    return
  }
  if (!consent.value) {
    toast.warning(isCertMode.value ? '请先勾选知情确认声明' : '请先勾选确认声明')
    return
  }
  if (!contactName.value.trim()) {
    toast.warning('请填写打印人姓名')
    return
  }
  if (!/^1[3-9]\d{9}$/.test(contactPhone.value.trim())) {
    toast.warning('请填写 11 位中国大陆手机号')
    return
  }
  submitting.value = true
  balanceShortage.value = false
  try {
    const printSettings = {
      copies: copies.value,
      merge_duplex: canDuplex.value ? duplex.value : false,
      contact_name: contactName.value.trim(),
      contact_phone: contactPhone.value.trim(),
    }
    if (colorSupported.value) printSettings.use_color = useColor.value
    const result = await createPayment({
      file_ids: [props.fileId],
      payment_method: 'balance',
      print_settings: printSettings,
    })
    toast.success('已扣费并发送打印')
    router.push(`/payment/${result.order_id}`)
  } catch (error) {
    if (error?.data?.detail === '请先登录' || /请先登录/.test(String(error?.message || ''))) {
      router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
      return
    }
    if (/余额不足/.test(String(error?.message || ''))) balanceShortage.value = true
    toast.error(error?.message || '下单失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="grid gap-4 sm:grid-cols-2">
      <div class="flex flex-col gap-2">
        <Label for="cert-copies">份数</Label>
        <Input id="cert-copies" v-model.number="copies" type="number" min="1" max="50" class="h-10" />
      </div>
      <div v-if="colorSupported" class="flex flex-col gap-2">
        <Label>打印颜色</Label>
        <Tabs :model-value="useColor ? 'color' : 'bw'" @update:model-value="(value) => (useColor = value === 'color')">
          <TabsList class="h-10!">
            <TabsTrigger value="bw" class="px-5 text-sm">黑白</TabsTrigger>
            <TabsTrigger value="color" class="px-5 text-sm">彩色</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
    </div>

    <!-- 双面打印（模块声明支持且打印机支持自动双面时展示；合计页数 <2 时禁用） -->
    <label
      v-if="duplexAvailable"
      class="flex w-fit cursor-pointer items-center gap-2.5 rounded-lg border px-3.5 py-2.5 transition-colors"
      :class="{ 'cursor-not-allowed opacity-60': !canDuplex }"
    >
      <Checkbox
        :model-value="duplex && canDuplex"
        :disabled="!canDuplex"
        @update:model-value="(checked) => (duplex = !!checked)"
      />
      <span class="text-sm font-semibold">双面打印</span>
      <span v-if="!canDuplex" class="text-xs text-muted-foreground">（仅 1 页时无需双面）</span>
    </label>

    <div class="grid gap-4 sm:grid-cols-2">
      <div class="flex flex-col gap-2">
        <Label for="cert-contact-name">打印人姓名</Label>
        <Input id="cert-contact-name" v-model="contactName" placeholder="下单联系人" class="h-10" maxlength="40" />
      </div>
      <div class="flex flex-col gap-2">
        <Label for="cert-contact-phone">手机号</Label>
        <Input id="cert-contact-phone" v-model="contactPhone" inputmode="numeric" placeholder="11 位手机号" class="h-10" maxlength="11" />
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-muted/30 px-3.5 py-3 text-sm">
      <span class="flex items-center gap-1.5">
        <Badge variant="secondary">{{ displayName }}</Badge>
        <span class="text-xs text-muted-foreground">{{ templatePriceText }}</span>
      </span>
      <span class="text-muted-foreground">
        预估金额 <span class="font-display text-base font-bold tabular-nums text-foreground">{{ amountText }}</span>
      </span>
      <span v-if="auth.user" class="flex items-center gap-1 text-muted-foreground">
        <Wallet class="size-4" aria-hidden="true" />
        余额 <span class="font-display tabular-nums text-foreground">¥{{ Number(auth.user.balance || 0).toFixed(2) }}</span>
      </span>
    </div>

    <!-- 知情确认：证照模块（证件合规声明）必选；文档类模块为普通确认 -->
    <label
      v-if="isCertMode"
      class="flex cursor-pointer items-start gap-2.5 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[13px] leading-relaxed"
    >
      <Checkbox
        :model-value="consent"
        class="mt-0.5"
        @update:model-value="(checked) => (consent = !!checked)"
      />
      <span>{{ CERT_CONSENT_TEXT }}；证件照片仅用于本次生成，不会被保存。</span>
    </label>
    <label v-else class="flex cursor-pointer items-start gap-2.5 rounded-lg border bg-muted/30 p-3 text-[13px] leading-relaxed">
      <Checkbox
        :model-value="consent"
        class="mt-0.5"
        @update:model-value="(checked) => (consent = !!checked)"
      />
      <span>已确认打印内容与预览一致，知晓打印件按两页合一版式输出。</span>
    </label>

    <Alert v-if="balanceShortage" variant="destructive">
      <CircleAlert class="size-4" aria-hidden="true" />
      <AlertTitle>余额不足</AlertTitle>
      <AlertDescription class="flex flex-wrap items-center gap-2">
        <span>请先充值后再打印（充值后回到本页继续下单）。</span>
        <Button as-child size="sm" variant="outline" class="h-8">
          <RouterLink to="/user/dashboard">去充值</RouterLink>
        </Button>
      </AlertDescription>
    </Alert>

    <Button class="h-11 w-full text-base font-semibold" :disabled="!consent || submitting" @click="confirmPrint">
      {{ submitting ? '正在提交…' : '确认打印' }}
    </Button>
    <p class="text-center text-xs text-muted-foreground">未勾选确认时无法打印；扣费成功后自动派发打印。</p>
  </div>
</template>
