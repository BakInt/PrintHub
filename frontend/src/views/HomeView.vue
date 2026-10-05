<template>
  <section class="workspace-grid">
    <div v-if="promotionNotices.length" class="promo-stack">
      <div v-for="notice in promotionNotices" :key="notice.title" class="promo-banner">
        <strong>{{ notice.title }}</strong>
        <span>{{ notice.message }}</span>
      </div>
    </div>

    <div class="panel upload-panel">
      <div class="section-heading">
        <div class="hero-copy">
          <p class="eyebrow">在线打印</p>
        </div>
        <Printer class="heading-icon" :size="32" />
      </div>

      <div v-if="!auth.user" class="guest-intro">
        <div class="guest-intro-copy">
          <strong>未登录也能打印</strong>
          <span>先上传文件并填写联系人即可创建支付订单，登录后可管理余额和历史记录。</span>
        </div>
        <RouterLink class="secondary-btn" to="/login">登录 / 注册</RouterLink>
      </div>

      <label class="dropzone" :class="{ active: dragging }" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="handleDrop">
        <UploadCloud :size="34" />
        <span>拖拽文件到这里，或点击选择</span>
        <small>支持 PDF、Office 文档和常见图片，{{ uploadLimitText }}</small>
        <input type="file" multiple @change="handleSelect" />
      </label>

      <div v-if="message" class="notice" :class="noticeType">{{ message }}</div>

      <div v-if="!files.length" class="empty-state-grid">
        <article class="empty-state-card">
          <span class="step-badge">1</span>
          <strong>上传打印文件</strong>
          <p>系统会自动完成格式转换、页数统计和安全检测。</p>
        </article>
        <article class="empty-state-card">
          <span class="step-badge">2</span>
          <strong>填写打印信息</strong>
          <p>设置份数、单双面和联系人，右侧会实时计算预计金额。</p>
        </article>
        <article class="empty-state-card">
          <span class="step-badge">3</span>
          <strong>支付后进入打印流程</strong>
          <p>支持微信、支付宝支付；登录用户还可以使用余额直接支付。</p>
        </article>
      </div>

      <div class="file-list">
        <article v-for="file in files" :key="file.file_id" class="file-row" :class="{ blocked: !file.safe }">
          <FileText :size="22" />
          <div>
            <strong>{{ file.file_name }}</strong>
            <span>{{ file.page_count }} 页 · {{ file.file_size }} MB · 黑色覆盖率 {{ file.black_coverage }}%</span>
            <div class="file-badges">
              <span :class="['badge', file.converted ? 'success' : 'info']">{{ file.converted ? '已转换为 PDF' : '原始 PDF' }}</span>
              <span v-if="file.safe" class="badge info">点击小眼睛预览 PDF</span>
            </div>
            <!-- 【新增功能】自动双面：打印机未开启「支持自动双面打印」时，这里完全隐藏。 -->
            <label
              v-if="file.safe && autoDuplexSupported"
              class="file-duplex"
              :class="{ disabled: !fileDuplexAvailable(file) }"
              @click="handleFileDuplexClick($event, file)"
            >
              <input
                type="checkbox"
                :checked="!!fileDuplex[file.file_id]"
                :disabled="!fileDuplexAvailable(file)"
                @change="setFileDuplex(file, $event.target.checked)"
              />
              <span>自动双面（本份文档正反面）</span>
            </label>
            <small v-if="file.safe && autoDuplexSupported && !fileDuplexAvailable(file)" class="field-hint">单页文档无法双面，仅按单面打印。</small>
          </div>
          <div class="file-actions">
            <button class="icon-btn" title="预览" :disabled="!file.safe" @click="openPreview(file)"><Eye :size="18" /></button>
            <button class="icon-btn danger" title="移除" @click="removeFile(file.file_id)"><Trash2 :size="18" /></button>
          </div>
        </article>
      </div>
      <p v-if="safeFiles.length && autoDuplexSupported" class="duplex-help">
        自动双面按每份文档独立设置：勾选后仅把该份多页文档的内容打印在同一张纸的正反两面。单页文档无法双面，也不会把多份文档合并到同一张纸上。
      </p>
    </div>

    <aside class="panel settings-panel">
      <h2>打印设置</h2>
      <div v-if="auth.user" class="bound-contact">
        <div class="section-heading compact contact-heading">
          <span>打印联系人</span>
          <RouterLink class="text-btn" to="/user/dashboard">修改</RouterLink>
        </div>
        <div v-if="profileContactComplete" class="contact-summary">
          <strong>{{ contactName }}</strong>
          <span>{{ contactPhone }}</span>
        </div>
        <div v-else class="notice warning compact-notice">
          请先在个人中心绑定姓名和手机号，系统会自动填写打印联系人。
        </div>
      </div>
      <template v-else>
        <label class="field-label">打印人姓名</label>
        <input v-model.trim="guestContactName" class="input" maxlength="40" placeholder="请输入打印人姓名" />

        <label class="field-label">联系电话</label>
        <input v-model="guestContactPhone" class="input" type="tel" inputmode="numeric" maxlength="11" placeholder="请输入 11 位手机号" @input="sanitizeContactPhone" />
        <small v-if="guestContactPhone && !contactPhoneValid" class="field-hint warning">请输入 11 位中国大陆手机号</small>
      </template>

      <!-- 【新增功能】自动双面选项：仅当后台把当前打印机配置为「支持自动双面打印」时展示，否则完全隐藏。 -->
      <div v-if="safeFiles.length && autoDuplexSupported" class="duplex-control">
        <div class="section-heading compact duplex-heading">
          <span class="duplex-title">
            自动双面
            <span class="duplex-tip" title="批量控制所有文档的自动双面。仅对页数不少于 2 页的文档生效，单页文档始终按单面打印，不会与其它文档合并到同一张纸。">
              <Info :size="14" />
            </span>
          </span>
          <span class="duplex-count">{{ duplexSummary.enabled }}/{{ duplexSummary.available }} 份已双面</span>
        </div>
        <div class="segmented duplex-methods">
          <button
            type="button"
            :class="{ selected: duplexSummary.available > 0 && duplexSummary.allOn }"
            :disabled="!duplexSummary.available"
            title="将所有页数不少于 2 页的文档设为双面打印（单页文档保持单面）"
            @click="setAllDuplex(true)"
          >
            打开所有
          </button>
          <button
            type="button"
            :class="{ selected: duplexSummary.allOff }"
            title="将所有文档恢复为单面打印"
            @click="setAllDuplex(false)"
          >
            关闭所有
          </button>
        </div>
        <small class="field-hint">仅对页数 ≥ 2 页的文档生效；单页文档始终按单面打印。可在左侧文件列表逐份微调。</small>
      </div>

      <!-- 【新增功能】彩色打印：仅当后台把当前打印机配置为「支持彩色打印」时展示，否则完全隐藏。 -->
      <div v-if="colorSupported" class="duplex-control color-control">
        <div class="section-heading compact duplex-heading">
          <span class="duplex-title">彩色打印</span>
        </div>
        <div class="segmented color-methods">
          <button type="button" :class="{ selected: !useColor }" title="按原有黑白流程处理并打印" @click="useColor = false">黑白</button>
          <button type="button" :class="{ selected: useColor }" title="保留文件原始色彩直接送给打印机，不做黑白转换" @click="useColor = true">彩色</button>
        </div>
      </div>

      <label class="field-label">份数</label>
      <input v-model.number="copies" class="input" type="number" min="1" max="99" />

      <label class="field-label">支付方式</label>
      <div class="segmented payment-methods">
        <button :class="{ selected: paymentMethod === 'wxpay' }" @click="paymentMethod = 'wxpay'">微信</button>
        <button :class="{ selected: paymentMethod === 'alipay' }" @click="paymentMethod = 'alipay'">支付宝</button>
        <button :class="{ selected: paymentMethod === 'balance' }" :disabled="!auth.user" @click="paymentMethod = 'balance'">余额</button>
      </div>
      <small v-if="!auth.user" class="field-hint">余额支付仅对已登录用户开放，当前可直接使用微信或支付宝下单。</small>

      <div class="price-box">
        <div class="price-breakdown">
          <span>预计金额</span>
          <small v-if="estimateDetail.discount_amount > 0">原价 ¥{{ Number(estimateDetail.base_amount || 0).toFixed(2) }} · 已优惠 ¥{{ Number(estimateDetail.discount_amount || 0).toFixed(2) }}</small>
          <small v-if="estimateDetail.applied_discount">{{ estimateDetail.applied_discount.label }} · {{ estimateDetail.sheet_count || 0 }} 张</small>
        </div>
        <strong>¥{{ estimatedAmount.toFixed(2) }}</strong>
      </div>

      <button class="primary-btn full desktop-submit" :disabled="!canSubmit || submitting" @click="createOrder">
        <CreditCard :size="18" />
        {{ submitting ? '提交中...' : paymentMethod === 'balance' ? '余额支付并打印' : '创建支付订单' }}
      </button>
    </aside>

    <div class="mobile-submit-bar">
      <div class="mobile-price">
        <span>预计金额</span>
        <strong>¥{{ estimatedAmount.toFixed(2) }}</strong>
        <small v-if="estimateDetail.discount_amount > 0">已优惠 ¥{{ Number(estimateDetail.discount_amount || 0).toFixed(2) }}</small>
      </div>
      <button class="primary-btn" :disabled="!canSubmit || submitting" @click="createOrder">
        <CreditCard :size="18" />
        {{ submitting ? '提交中...' : paymentMethod === 'balance' ? '余额支付' : '去支付' }}
      </button>
    </div>

    <div v-if="preview" class="panel preview-panel">
      <div class="section-heading compact">
        <h2>PDF 预览</h2>
        <span>浏览器内预览 PDF（非 PDF 文件已自动转换）</span>
      </div>
      <iframe :src="preview" title="PDF 预览"></iframe>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { CreditCard, Eye, FileText, Info, Printer, Trash2, UploadCloud } from 'lucide-vue-next'
import { buildApiUrl, request } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatOrderCreatedQueueMessage } from '../utils/queue'

const router = useRouter()
const auth = useAuthStore()
const files = ref([])
const preview = ref('')
const guestContactName = ref('')
const guestContactPhone = ref('')
const copies = ref(1)
const fileDuplex = ref({})
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

const safeFiles = computed(() => files.value.filter((file) => file.safe))
// 【新增功能】打印机能力完全由后台「打印机管理」的配置驱动，前端不硬编码：
// 只有 is_support_color/is_support_auto_duplex 为 true 时才展示对应选项。
const colorSupported = computed(() => printOptions.value?.is_support_color === true)
const autoDuplexSupported = computed(() => printOptions.value?.is_support_auto_duplex === true)
function fileDuplexAvailable(file) {
  return (Number(file.page_count) || 0) >= 2
}
function fileSettingsPayload() {
  return safeFiles.value.map((file) => ({
    file_id: file.file_id,
    double_sided: autoDuplexSupported.value && fileDuplexAvailable(file) && !!fileDuplex.value[file.file_id],
  }))
}
function setFileDuplex(file, checked) {
  if (!fileDuplexAvailable(file)) return
  fileDuplex.value = { ...fileDuplex.value, [file.file_id]: !!checked }
}
function handleFileDuplexClick(event, file) {
  if (fileDuplexAvailable(file)) return
  event.preventDefault()
  setNotice('该文档仅有一页，无法双面打印，将按单面处理。', 'warning')
}
const duplexSummary = computed(() => {
  const available = safeFiles.value.filter((file) => fileDuplexAvailable(file))
  const enabled = available.filter((file) => !!fileDuplex.value[file.file_id])
  return {
    available: available.length,
    enabled: enabled.length,
    allOn: available.length > 0 && enabled.length === available.length,
    allOff: enabled.length === 0,
  }
})
function setAllDuplex(on) {
  // 「打开所有」只对页数 ≥ 2 的文档生效，单页文档始终单面（后端会拒绝单页双面）。
  const next = { ...fileDuplex.value }
  for (const file of safeFiles.value) {
    next[file.file_id] = on && fileDuplexAvailable(file)
  }
  fileDuplex.value = next
}
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

watch([safeFiles, copies, fileDuplex, printOptions], async () => {
  const fileIds = safeFiles.value.map((file) => file.file_id)
  if (!fileIds.length) {
    estimatedAmount.value = 0
    estimateDetail.value = {}
    return
  }
  const data = await request('/api/price', {
    method: 'POST',
    body: { file_ids: fileIds, copies: copies.value, file_settings: fileSettingsPayload() },
  })
  estimatedAmount.value = data.amount
  estimateDetail.value = data
}, { deep: true })

async function loadPromotions() {
  try {
    promotions.value = await request('/api/promotions')
  } catch {
    promotions.value = null
  }
}

async function loadLimits() {
  try {
    uploadLimits.value = await request('/api/limits')
  } catch {
    uploadLimits.value = null
  }
}

// 【新增功能】读取当前（默认）打印机的彩色/自动双面能力，用于条件渲染「彩色打印」「双面打印」。
async function loadPrintOptions() {
  try {
    const data = await request('/api/print-options')
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
  // 检测到 ≥ 2 页的安全文档时默认启用自动双面（仅在打印机支持自动双面时）；单页文档保持单面。
  if (autoDuplexSupported.value && result.data.safe && (Number(result.data.page_count) || 0) >= 2) {
    fileDuplex.value = { ...fileDuplex.value, [result.data.file_id]: true }
  }
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
  if (fileDuplex.value[fileId]) {
    const next = { ...fileDuplex.value }
    delete next[fileId]
    fileDuplex.value = next
  }
  if (preview.value.includes(fileId)) preview.value = ''
}

function openPreview(file) {
  if (!file.safe) return
  preview.value = file.preview_url
}

async function submitPrintOrder(method) {
  const printSettings = {
    copies: copies.value,
    file_settings: fileSettingsPayload(),
    contact_name: contactName.value.trim(),
    contact_phone: contactPhone.value
  }
  // 【新增功能】只在打印机确实支持对应能力时才携带新参数：
  // use_color 决定后端是否跳过黑白化处理（true=原样送印），use_auto_duplex 表示用户是否选择了自动双面。
  if (colorSupported.value) printSettings.use_color = useColor.value
  if (autoDuplexSupported.value) printSettings.use_auto_duplex = duplexSummary.value.enabled > 0
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
