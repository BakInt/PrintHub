<template>
  <section class="mx-auto w-full max-w-md py-2">
    <Card class="py-6">
      <CardHeader class="grid gap-1.5">
        <p class="text-[13px] font-bold tracking-widest text-primary">收银台</p>
        <CardTitle class="font-display text-2xl tracking-tight">订单支付与打印状态</CardTitle>
      </CardHeader>
      <CardContent class="grid gap-4">
        <div v-if="order" class="grid gap-2.5">
          <div class="flex items-center justify-between gap-3 rounded-lg border bg-muted/50 px-3.5 py-2.5 text-sm">
            <span class="text-muted-foreground">订单号</span>
            <strong class="break-all text-foreground">{{ order.id }}</strong>
          </div>
          <div class="flex items-center justify-between gap-3 rounded-lg border bg-muted/50 px-3.5 py-2.5 text-sm">
            <span class="text-muted-foreground">金额</span>
            <strong class="font-display text-base text-primary tabular-nums">¥{{ Number(order.total_amount).toFixed(2) }}</strong>
          </div>
          <div class="flex items-center justify-between gap-3 rounded-lg border bg-muted/50 px-3.5 py-2.5 text-sm">
            <span class="text-muted-foreground">状态</span>
            <strong class="text-foreground">{{ statusText[order.status] || order.status }}</strong>
          </div>
          <Alert v-if="queueMessage" class="border-primary/25 bg-accent text-accent-foreground">
            <Info class="size-4" />
            <AlertDescription class="text-accent-foreground">{{ queueMessage }}</AlertDescription>
          </Alert>
          <Alert v-if="order.print_error" class="border-warning/30 bg-warning/10 text-warning">
            <TriangleAlert class="size-4" />
            <AlertDescription class="text-warning">{{ order.print_error }}</AlertDescription>
          </Alert>
        </div>
        <div class="grid place-items-center gap-3 rounded-xl border border-dashed bg-muted/40 px-6 py-10 text-center text-muted-foreground">
          <QrCode class="size-16 opacity-70" aria-hidden="true" />
          <span class="max-w-64 text-[13px] leading-relaxed">微信或支付宝订单创建后会跳转到配置的易支付网关</span>
        </div>
        <Button variant="secondary" class="h-10" @click="loadOrder">
          <RefreshCw />
          刷新状态
        </Button>
      </CardContent>
    </Card>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Info, QrCode, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import { request } from '@/api/client'
import { formatQueueMessage } from '@/utils/queue'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const route = useRoute()
const order = ref(null)
const statusText = { pending: '待支付', paid: '已支付', printing: '已发送打印', print_failed: '打印失败', completed: '已完成' }

const queueMessage = computed(() => formatQueueMessage(order.value?.queue, order.value?.status))

async function loadOrder() {
  order.value = await request(`/api/orders/${route.params.orderId}`)
}

onMounted(loadOrder)
</script>
