<template>
  <section class="account-dashboard" :class="mobileTabClass">
    <div class="account-sidebar">
      <aside class="panel account-summary-panel">
        <p class="eyebrow">个人中心</p>
        <h1>{{ auth.user?.username || '用户' }}</h1>
        <div class="metric-card balance-card">
          <span>账户余额</span>
          <strong>¥{{ formatMoney(auth.user?.balance || 0) }}</strong>
        </div>
        <button class="secondary-btn" @click="refreshDashboard" :disabled="loading">
          <RefreshCw :size="18" />刷新余额
        </button>
      </aside>

      <section class="panel profile-panel" :class="{ 'profile-collapsed': profileCollapsed }">
        <!-- 手机端：已绑定且非编辑态时折叠为摘要卡，点「修改」再展开表单；桌面端始终展开表单 -->
        <div class="profile-summary" v-if="profileComplete">
          <div class="section-heading compact profile-heading">
            <h2>打印联系人</h2>
            <span class="badge success">已绑定</span>
          </div>
          <div class="profile-summary-body">
            <div class="profile-summary-info">
              <span class="profile-summary-name">{{ auth.user?.real_name }}</span>
              <span class="profile-summary-phone">{{ maskPhone(auth.user?.phone) }}</span>
            </div>
            <button class="secondary-btn small" type="button" @click="startEditProfile">
              <Pencil :size="16" />修改
            </button>
          </div>
        </div>
        <form class="profile-form" @submit.prevent="saveProfile">
          <div class="section-heading compact profile-heading">
            <h2>打印联系人</h2>
            <span :class="['badge', profileComplete ? 'success' : 'warning']">{{ profileComplete ? '已绑定' : '未绑定' }}</span>
          </div>
          <label class="field-label">
            姓名
            <input v-model.trim="profileForm.real_name" class="input" maxlength="40" placeholder="请输入姓名" />
          </label>
          <label class="field-label">
            手机号
            <input v-model="profileForm.phone" class="input" type="tel" inputmode="numeric" maxlength="11" placeholder="请输入 11 位手机号" @input="sanitizeProfilePhone" />
          </label>
          <small v-if="profileForm.phone && !profilePhoneValid" class="field-hint warning">请输入 11 位中国大陆手机号</small>
          <div class="profile-actions">
            <button v-if="profileComplete" class="secondary-btn" type="button" @click="cancelEditProfile">取消</button>
            <button class="primary-btn full" type="submit" :disabled="savingProfile">
              {{ savingProfile ? '保存中...' : '保存联系人' }}
            </button>
          </div>
        </form>
        <div v-if="feedback" :class="['notice', feedbackType]">{{ feedback }}</div>
      </section>
    </div>

    <div class="account-main">
      <section class="panel recharge-panel">
        <div class="section-heading compact">
          <div>
            <p class="eyebrow">账户充值</p>
            <h2>余额充值</h2>
          </div>
          <span class="recharge-bill-badge">账单</span>
        </div>

        <div class="recharge-stats">
          <div>
            <strong>¥{{ formatMoney(auth.user?.balance || 0) }}</strong>
            <span>当前余额</span>
          </div>
          <div>
            <strong>¥{{ formatMoney(totalSpent) }}</strong>
            <span>历史消费</span>
          </div>
          <div>
            <strong>{{ ordersTotal }}</strong>
            <span>请求次数</span>
          </div>
        </div>

        <form class="recharge-form" @submit.prevent="submitRecharge">
          <label class="field-label">
            充值数量
            <input v-model.number="rechargeAmount" class="input amount-input" type="number" min="1" max="2000" step="0.01" />
          </label>

          <div class="field-label">
            选择支付方式
            <div class="segmented recharge-methods">
              <button type="button" :class="{ selected: paymentMethod === 'alipay' }" @click="paymentMethod = 'alipay'">
                支付宝
              </button>
              <button type="button" :class="{ selected: paymentMethod === 'wxpay' }" @click="paymentMethod = 'wxpay'">
                微信
              </button>
            </div>
          </div>

          <div class="preset-section">
            <div class="preset-heading">
              <strong>选择充值额度</strong>
              <span>充值金额将按 1:1 计入余额</span>
            </div>
            <div class="recharge-presets">
              <button
                v-for="amount in presetAmounts"
                :key="amount"
                type="button"
                :class="['recharge-preset', { selected: Number(rechargeAmount) === amount }]"
                @click="rechargeAmount = amount"
              >
                <span class="preset-icon">¥</span>
                <strong>{{ amount }} ¥</strong>
                <small>实付 ¥{{ formatMoney(amount) }}</small>
              </button>
            </div>
          </div>

          <button class="primary-btn full" type="submit" :disabled="submitting">
            {{ submitting ? '创建中...' : `充值 ¥${formatMoney(normalizedAmount)}` }}
          </button>
        </form>

        <section class="voucher-panel">
          <h3>兑换码充值</h3>
          <div class="voucher-row">
            <input class="input" type="text" placeholder="请输入兑换码" disabled />
            <button class="secondary-btn" disabled>兑换额度</button>
          </div>
          <small>兑换码充值暂未开放</small>
        </section>
      </section>

      <section class="panel wide-panel orders-panel">
        <div class="section-heading compact">
          <h2>最近订单</h2>
          <button class="secondary-btn small" @click="loadOrders" :disabled="loading">刷新</button>
        </div>
        <div v-if="orders.length === 0 && !loading" class="empty-preview compact-empty">暂无订单</div>
        <article v-for="order in orders" :key="order.id" class="table-row account-order-row">
          <span>{{ order.id }}</span>
          <strong>¥{{ formatMoney(order.total_amount) }}</strong>
          <span>{{ formatOrderType(order.order_type) }}</span>
          <span>{{ statusText[order.status] || order.status }}</span>
        </article>
        <div v-if="orders.length > 0" class="orders-more">
          <button v-if="hasMore" class="secondary-btn load-more-btn" @click="loadMoreOrders" :disabled="loadingMore">
            <RefreshCw v-if="loadingMore" :size="16" class="spin" />
            {{ loadingMore ? '加载中...' : '加载更多' }}
          </button>
          <p v-else class="orders-all-loaded">已显示全部订单</p>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { RefreshCw, Pencil } from 'lucide-vue-next'
import { buildApiUrl, request } from '../api/client'
import { useAuthStore } from '../stores/auth'

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
const mobileTabClass = computed(() => (route.query.tab === 'orders' ? 'mobile-tab-orders' : 'mobile-tab-me'))

// 历史消费与请求次数使用后端全量统计，不随分页加载变化。
const totalSpent = computed(() => totalSpentAmount.value)
const profilePhoneValid = computed(() => phonePattern.test(profileForm.value.phone))
const profileComplete = computed(() => Boolean(auth.user?.real_name && phonePattern.test(auth.user?.phone || '')))
// 已绑定且未进入编辑态时折叠联系人（仅手机端通过 CSS 生效；桌面端始终展开表单）
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
