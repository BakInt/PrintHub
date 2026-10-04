<template>
  <section class="payment-layout">
    <div class="panel payment-card">
      <p class="eyebrow">收银台</p>
      <h1>订单支付与打印状态</h1>
      <div v-if="order" class="status-stack">
        <div class="status-line"><span>订单号</span><strong>{{ order.id }}</strong></div>
        <div class="status-line"><span>金额</span><strong>¥{{ Number(order.total_amount).toFixed(2) }}</strong></div>
        <div class="status-line"><span>状态</span><strong>{{ statusText[order.status] || order.status }}</strong></div>
        <div v-if="queueMessage" class="notice info">{{ queueMessage }}</div>
        <div v-if="order.print_error" class="notice warning">{{ order.print_error }}</div>
      </div>
      <div class="qr-placeholder">
        <QrCode :size="76" />
        <span>微信或支付宝订单创建后会跳转到配置的易支付网关</span>
      </div>
      <button class="secondary-btn" @click="loadOrder"><RefreshCw :size="18" />刷新状态</button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { QrCode, RefreshCw } from 'lucide-vue-next'
import { request } from '../api/client'
import { formatQueueMessage } from '../utils/queue'

const route = useRoute()
const order = ref(null)
const statusText = { pending: '待支付', paid: '已支付', printing: '已发送打印', print_failed: '打印失败', completed: '已完成' }

const queueMessage = computed(() => formatQueueMessage(order.value?.queue, order.value?.status))

async function loadOrder() {
  order.value = await request(`/api/orders/${route.params.orderId}`)
}

onMounted(loadOrder)
</script>
