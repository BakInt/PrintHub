<template>
  <section class="grid gap-4 lg:items-start lg:gap-6" :class="isOrdersTab ? '' : 'lg:grid-cols-[minmax(280px,330px)_minmax(0,1fr)]'">
    <!-- 左列：个人中心摘要 + 打印联系人（tab=orders 时整列隐藏，桌面与手机一致） -->
    <div v-if="!isOrdersTab" class="grid gap-4 lg:sticky lg:top-20">
      <!-- 账户摘要 -->
      <Card class="py-5">
        <CardHeader class="grid gap-1.5 pb-1">
          <p class="text-[13px] font-bold tracking-widest text-primary">个人中心</p>
          <CardTitle class="font-display text-2xl tracking-tight">{{ auth.user?.username || '用户' }}</CardTitle>
        </CardHeader>
        <CardContent class="grid gap-3">
          <div class="rounded-xl border border-primary/25 bg-accent/70 p-4">
            <span class="text-[13px] text-muted-foreground">账户余额</span>
            <strong class="block font-display text-3xl font-bold tracking-tight text-primary tabular-nums">
              ¥{{ formatMoney(auth.user?.balance || 0) }}
            </strong>
          </div>
          <Button variant="secondary" class="h-10" @click="refreshDashboard" :disabled="loading">
            <RefreshCw />
            刷新余额
          </Button>
        </CardContent>
      </Card>

      <!-- 打印联系人：手机端已绑定且非编辑态时折叠为摘要卡，桌面端始终展开表单 -->
      <Card class="py-5">
        <CardHeader class="pb-0">
          <CardTitle class="flex items-center gap-2 font-display text-lg">
            打印联系人
            <Badge :class="profileComplete ? 'border-transparent bg-success/10 text-success' : 'border-transparent bg-warning/15 text-warning'">
              {{ profileComplete ? '已绑定' : '未绑定' }}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent class="grid gap-3">
          <!-- 手机端折叠摘要（桌面端隐藏） -->
          <div v-if="profileComplete" class="grid gap-2.5 rounded-xl border bg-muted/50 p-3.5 md:hidden">
            <div class="grid min-w-0 gap-0.5">
              <span class="truncate font-semibold text-foreground">{{ auth.user?.real_name }}</span>
              <span class="text-sm text-muted-foreground">{{ maskPhone(auth.user?.phone) }}</span>
            </div>
            <Button variant="secondary" size="sm" class="h-9 w-fit" type="button" @click="startEditProfile">
              <Pencil />
              修改
            </Button>
          </div>
          <form class="grid gap-3" :class="profileCollapsed ? 'max-md:hidden' : ''" @submit.prevent="saveProfile">
            <div class="grid gap-1.5">
              <Label for="profile-name" class="text-sm font-bold">姓名</Label>
              <Input id="profile-name" v-model.trim="profileForm.real_name" maxlength="40" placeholder="请输入姓名" class="h-10" />
            </div>
            <div class="grid gap-1.5">
              <Label for="profile-phone" class="text-sm font-bold">手机号</Label>
              <Input
                id="profile-phone"
                v-model="profileForm.phone"
                type="tel"
                inputmode="numeric"
                maxlength="11"
                placeholder="请输入 11 位手机号"
                class="h-10"
                @input="sanitizeProfilePhone"
              />
              <small v-if="profileForm.phone && !profilePhoneValid" class="text-xs text-destructive">
                请输入 11 位中国大陆手机号
              </small>
            </div>
            <div class="flex gap-2">
              <Button v-if="profileComplete" variant="secondary" type="button" class="h-10" @click="cancelEditProfile">取消</Button>
              <Button type="submit" class="h-10 flex-1 font-bold" :disabled="savingProfile">
                {{ savingProfile ? '保存中...' : '保存联系人' }}
              </Button>
            </div>
          </form>
          <Alert
            v-if="feedback"
            :class="feedbackType === 'warning'
              ? 'border-warning/30 bg-warning/10 text-warning'
              : 'border-success/30 bg-success/10 text-success'"
          >
            <TriangleAlert v-if="feedbackType === 'warning'" class="size-4" />
            <CircleCheck v-else class="size-4" />
            <AlertDescription :class="feedbackType === 'warning' ? 'text-warning' : 'text-success'">{{ feedback }}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    </div>

    <!-- 右列：充值 + 订单 -->
    <div class="grid gap-4 lg:gap-6">
      <!-- 余额充值（tab=orders 时隐藏） -->
      <Card v-if="!isOrdersTab" class="gap-4 py-5">
        <CardHeader class="flex-row items-center justify-between gap-3 pb-0">
          <div class="grid gap-1">
            <p class="text-[13px] font-bold tracking-widest text-primary">账户充值</p>
            <CardTitle class="font-display text-xl">余额充值</CardTitle>
          </div>
          <Badge variant="secondary">账单</Badge>
        </CardHeader>
        <CardContent class="grid gap-4">
          <div class="grid gap-3 rounded-xl border bg-muted/50 p-4 sm:grid-cols-3">
            <div class="grid gap-0.5">
              <strong class="font-display text-2xl font-bold text-primary tabular-nums">¥{{ formatMoney(auth.user?.balance || 0) }}</strong>
              <span class="text-[13px] text-muted-foreground">当前余额</span>
            </div>
            <div class="grid gap-0.5">
              <strong class="font-display text-2xl font-bold text-foreground tabular-nums">¥{{ formatMoney(totalSpent) }}</strong>
              <span class="text-[13px] text-muted-foreground">历史消费</span>
            </div>
            <div class="grid gap-0.5">
              <strong class="font-display text-2xl font-bold text-foreground tabular-nums">{{ ordersTotal }}</strong>
              <span class="text-[13px] text-muted-foreground">请求次数</span>
            </div>
          </div>

          <form class="grid gap-4" @submit.prevent="submitRecharge">
            <div class="grid gap-1.5">
              <Label for="recharge-amount" class="text-sm font-bold">充值数量</Label>
              <Input id="recharge-amount" v-model.number="rechargeAmount" type="number" min="1" max="2000" step="0.01" class="h-10" />
            </div>

            <div class="grid gap-1.5">
              <Label class="text-sm font-bold">选择支付方式</Label>
              <Tabs :model-value="paymentMethod" @update:model-value="(value) => (paymentMethod = value)">
                <TabsList class="h-10! w-full!">
                  <TabsTrigger value="alipay" class="flex-1">支付宝</TabsTrigger>
                  <TabsTrigger value="wxpay" class="flex-1">微信</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>

            <div class="grid gap-2">
              <div class="flex items-baseline justify-between gap-2">
                <strong class="text-sm text-foreground">选择充值额度</strong>
                <span class="text-xs text-muted-foreground">充值金额将按 1:1 计入余额</span>
              </div>
              <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <button
                  v-for="amount in presetAmounts"
                  :key="amount"
                  type="button"
                  class="flex min-h-24 flex-col items-center justify-center gap-1 rounded-xl border p-3 text-center transition-colors hover:border-primary/50 hover:bg-accent/60"
                  :class="Number(rechargeAmount) === amount ? 'border-primary bg-accent text-accent-foreground shadow-sm' : 'bg-card text-muted-foreground'"
                  @click="rechargeAmount = amount"
                >
                  <strong class="font-display text-lg font-bold text-foreground tabular-nums">{{ amount }} ¥</strong>
                  <small class="text-xs">实付 ¥{{ formatMoney(amount) }}</small>
                </button>
              </div>
            </div>

            <Button type="submit" size="lg" class="h-11 w-full font-bold" :disabled="submitting">
              {{ submitting ? '创建中...' : `充值 ¥${formatMoney(normalizedAmount)}` }}
            </Button>
          </form>

          <!-- 兑换码充值 -->
          <div class="grid gap-2.5 rounded-xl border bg-muted/40 p-4">
            <h3 class="text-sm font-bold text-foreground">兑换码充值</h3>
            <div class="flex flex-col gap-2 sm:flex-row">
              <Input
                v-model.trim="redemptionCode"
                type="text"
                maxlength="64"
                placeholder="请输入兑换码"
                class="h-10 flex-1"
                @keyup.enter="submitRedemption"
              />
              <Button variant="secondary" class="h-10" :disabled="redeeming" @click="submitRedemption">
                {{ redeeming ? '兑换中...' : '兑换额度' }}
              </Button>
            </div>
            <small class="text-xs leading-relaxed text-muted-foreground">
              输入兑换码即可兑换相应面额到余额，可直接用于打印扣费
            </small>
          </div>
        </CardContent>
      </Card>

      <!-- 最近订单 -->
      <Card v-if="!isMineTab" class="gap-4 py-5">
        <CardHeader class="flex-row items-center justify-between gap-3 pb-0">
          <CardTitle class="font-display text-xl">最近订单</CardTitle>
          <Button variant="secondary" size="sm" class="h-8" @click="loadOrders" :disabled="loading">刷新</Button>
        </CardHeader>
        <CardContent class="grid gap-2">
          <div v-if="orders.length === 0 && !loading" class="rounded-lg border border-dashed bg-muted/40 px-4 py-8 text-center text-sm text-muted-foreground">
            暂无订单
          </div>
          <div
            v-for="order in orders"
            :key="order.id"
            class="grid gap-1 rounded-lg border bg-card p-3 text-sm max-md:bg-muted/30 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:items-center sm:gap-4"
          >
            <span class="break-all font-medium text-foreground">{{ order.id }}</span>
            <strong class="font-display text-primary tabular-nums">¥{{ formatMoney(order.total_amount) }}</strong>
            <span class="text-muted-foreground">{{ formatOrderType(order.order_type) }}</span>
            <span class="text-muted-foreground">{{ statusText[order.status] || order.status }}</span>
          </div>
          <div v-if="orders.length > 0" class="grid gap-2 pt-1">
            <Button v-if="hasMore" variant="secondary" class="h-10 w-full" @click="loadMoreOrders" :disabled="loadingMore">
              <RefreshCw :class="loadingMore ? 'animate-spin' : ''" />
              {{ loadingMore ? '加载中...' : '加载更多' }}
            </Button>
            <p v-else class="text-center text-xs text-muted-foreground">已显示全部订单</p>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 兑换码结果弹窗：成功 / 失败 -->
    <Dialog :open="!!redeemModal" @update:open="(value) => !value && closeRedeemModal()">
      <DialogContent class="max-sm:max-w-[calc(100vw-2rem)] sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{{ redeemModal?.type === 'success' ? '兑换成功' : '兑换失败' }}</DialogTitle>
          <DialogDescription class="sr-only">兑换码兑换结果提示</DialogDescription>
        </DialogHeader>
        <p
          class="text-sm leading-relaxed"
          :class="redeemModal?.type === 'success' ? 'text-success' : 'text-destructive'"
        >
          {{ redeemModal?.message }}
        </p>
        <DialogFooter>
          <Button class="h-10" @click="closeRedeemModal">确定</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { CircleCheck, Pencil, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import { buildApiUrl, request } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const auth = useAuthStore()
const route = useRoute()
const orders = ref([])
const ordersTotal = ref(0)
const totalSpentAmount = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)
const loading = ref(false)
const submitting = ref(false)
const savingProfile = ref(false)
const editingProfile = ref(false)
const rechargeAmount = ref(5)
const paymentMethod = ref('alipay')
const feedback = ref('')
const feedbackType = ref('success')
const profileForm = ref({ real_name: '', phone: '' })
// 兑换码充值
const redemptionCode = ref('')
const redeeming = ref(false)
const redeemModal = ref(null) // { type: 'success' | 'error', message }
const presetAmounts = [25, 50, 100, 200, 500, 1000, 1500, 2000]
const statusText = { pending: '待支付', paid: '已支付', printing: '已发送打印', print_failed: '打印失败', completed: '已完成' }
const phonePattern = /^1[3-9]\d{9}$/
const PAGE_SIZE = 10

const normalizedAmount = computed(() => {
  const amount = Number(rechargeAmount.value)
  return Number.isFinite(amount) ? Math.round(amount * 100) / 100 : 0
})

// 个人中心按 ?tab= 拆分「订单」和「个人中心」视图（桌面与手机端均生效，见 UI_ADAPTATION 第 4.1 节）：
// 订单只看最近订单，个人中心看余额/联系人/充值等其余内容。
const isOrdersTab = computed(() => route.query.tab === 'orders')
const isMineTab = computed(() => !isOrdersTab.value)

// 历史消费与请求次数使用后端全量统计，不随分页加载变化。
const totalSpent = computed(() => totalSpentAmount.value)
const profilePhoneValid = computed(() => phonePattern.test(profileForm.value.phone))
const profileComplete = computed(() => Boolean(auth.user?.real_name && phonePattern.test(auth.user?.phone || '')))
// 已绑定且未进入编辑态时折叠联系人（仅手机端通过响应式类生效；桌面端始终展开表单）
const profileCollapsed = computed(() => profileComplete.value && !editingProfile.value)

function maskPhone(phone) {
  const value = String(phone || '')
  return value.length === 11 ? `${value.slice(0, 3)}****${value.slice(7)}` : value
}

function startEditProfile() {
  syncProfileForm()
  editingProfile.value = true
}

function cancelEditProfile() {
  syncProfileForm()
  editingProfile.value = false
  feedback.value = ''
}

function formatMoney(value) {
  return Number(value || 0).toFixed(2)
}

function formatOrderType(type) {
  return { print: '打印', recharge: '充值', test: '测试' }[type || 'print'] || type || '订单'
}

function showFeedback(message, type = 'success') {
  feedback.value = message
  feedbackType.value = type
}

function syncProfileForm() {
  profileForm.value = {
    real_name: auth.user?.real_name || '',
    phone: auth.user?.phone || ''
  }
}

function sanitizeProfilePhone(event) {
  profileForm.value.phone = event.target.value.replace(/\D/g, '').slice(0, 11)
}

function applyOrdersPage(data) {
  // 兼容后端返回：新版为 {items,total,has_more,total_spent}，旧版为数组。
  if (Array.isArray(data)) {
    ordersTotal.value = data.length
    hasMore.value = false
    return data
  }
  ordersTotal.value = data.total ?? data.items?.length ?? 0
  hasMore.value = Boolean(data.has_more)
  totalSpentAmount.value = Number(data.total_spent || 0)
  return data.items || []
}

async function fetchFirstPage() {
  const data = await request(`/api/user/orders?limit=${PAGE_SIZE}&offset=0`)
  orders.value = applyOrdersPage(data)
}

async function loadOrders() {
  loading.value = true
  try {
    await fetchFirstPage()
  } finally {
    loading.value = false
  }
}

async function loadMoreOrders() {
  // 防重复请求：加载中或已无更多时直接返回。
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    const offset = orders.value.length
    const data = await request(`/api/user/orders?limit=${PAGE_SIZE}&offset=${offset}`)
    const newItems = applyOrdersPage(data)
    // 按 id 去重后追加，避免因新订单插入导致 offset 错位而重复。
    const existingIds = new Set(orders.value.map((order) => order.id))
    orders.value = [...orders.value, ...newItems.filter((order) => !existingIds.has(order.id))]
  } catch (error) {
    showFeedback(error.message || '加载更多订单失败', 'warning')
  } finally {
    loadingMore.value = false
  }
}

async function refreshDashboard() {
  loading.value = true
  try {
    await auth.loadMe()
    syncProfileForm()
    await fetchFirstPage()
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  if (!profileForm.value.real_name.trim()) {
    showFeedback('请填写姓名', 'warning')
    return
  }
  if (!profilePhoneValid.value) {
    showFeedback('请输入 11 位中国大陆手机号', 'warning')
    return
  }
  savingProfile.value = true
  try {
    await auth.updateProfile({
      real_name: profileForm.value.real_name.trim(),
      phone: profileForm.value.phone
    })
    syncProfileForm()
    editingProfile.value = false
    showFeedback('联系人已保存，打印时会自动填写')
  } catch (error) {
    showFeedback(error.message || '保存联系人失败', 'warning')
  } finally {
    savingProfile.value = false
  }
}

async function submitRecharge() {
  const amount = normalizedAmount.value
  if (!Number.isFinite(amount) || amount < 1 || amount > 2000) {
    showFeedback('充值金额需在 1 到 2000 元之间', 'warning')
    return
  }
  submitting.value = true
  try {
    const data = await request('/api/user/recharge', {
      method: 'POST',
      body: { amount, payment_method: paymentMethod.value }
    })
    window.location.href = buildApiUrl(data.qr_code_url)
  } catch (error) {
    showFeedback(error.message || '创建充值订单失败', 'warning')
  } finally {
    submitting.value = false
  }
}

async function submitRedemption() {
  const code = redemptionCode.value.trim()
  if (!code) {
    redeemModal.value = { type: 'error', message: '请输入兑换码' }
    return
  }
  redeeming.value = true
  try {
    const data = await request('/api/user/redeem', { method: 'POST', body: { code } })
    redemptionCode.value = ''
    // 后端返回最新余额，直接同步到用户信息，无需再请求一次。
    if (data && auth.user && typeof data.balance === 'number') {
      auth.user = { ...auth.user, balance: data.balance }
    }
    redeemModal.value = {
      type: 'success',
      message: `兑换成功，¥${formatMoney(data.amount)} 已加入余额，当前余额 ¥${formatMoney(data.balance)}`
    }
  } catch (error) {
    // 业务错误（兑换码不存在 / 已过期 / 可用次数已用完等）直接用后端返回的中文提示；
    // 只有拿不到可读信息、或确属未知服务器故障时，才统一提示服务器异常。
    const message = String(error?.message || '').trim()
    const unknownServerError = !message || /internal server error|服务器内部错误|^请求失败$/i.test(message)
    redeemModal.value = {
      type: 'error',
      message: unknownServerError ? '兑换失败，服务器异常，请稍后重试' : message
    }
  } finally {
    redeeming.value = false
  }
}

function closeRedeemModal() {
  redeemModal.value = null
}

async function loadRechargeReturnStatus() {
  const orderId = route.query.recharge_order
  if (!orderId) return
  try {
    const order = await request(`/api/orders/${orderId}`)
    if (order.status === 'paid') {
      await refreshDashboard()
      showFeedback(`充值 ¥${formatMoney(order.total_amount)} 已到账`)
    } else {
      showFeedback(`充值订单 ${statusText[order.status] || order.status}`, order.status === 'pending' ? 'warning' : 'success')
    }
  } catch (error) {
    showFeedback(error.message || '充值状态查询失败', 'warning')
  }
}

onMounted(async () => {
  syncProfileForm()
  await refreshDashboard()
  await loadRechargeReturnStatus()
})
</script>
