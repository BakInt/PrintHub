<script setup>
// /cert 证照门户页：功能宫格完全由 GET /api/cert/templates 驱动（模板启停即时生效），
// 「图文打印」静态卡排首位指向现有首页；接口异常显示重试空态、不影响静态卡。
// 配色不写死色值；手机端 2 列、md 3 列、xl 4 列；320px 无横向滚动。
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { CircleAlert, ShieldCheck } from 'lucide-vue-next'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { CERT_PRIVACY_NOTE, certModuleRoute } from './constants'
import { fetchCertTemplates } from './api'
import PortalCard from './components/PortalCard.vue'

const templates = ref([])
const loading = ref(true)
const loadError = ref(false)

async function load() {
  loading.value = true
  loadError.value = false
  try {
    templates.value = await fetchCertTemplates()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)

function priceTextOf(template) {
  if (template.price_mode !== 'template' || template.price == null) return '按页计价'
  // 全部模板统一按「页」计独立单价（证照件 1 页/版，doc2up 按版面数）。
  return `¥${Number(template.price).toFixed(2)}/页`
}

function onUnavailableCard() {
  toast.info('该功能页面暂未开放，请稍后再试')
}
</script>

<template>
  <div class="mx-auto w-full max-w-7xl px-3 py-6 sm:px-6">
    <div class="mb-6">
      <p class="text-[13px] font-bold tracking-widest text-primary">证照打印</p>
      <h1 class="mt-1 font-display text-2xl font-bold tracking-tight sm:text-3xl">证件拍照即打印，标准尺寸不走样</h1>
      <p class="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        选择功能卡片进入对应打印页：拍摄证件照片，系统自动裁剪矫正，按模板排成尺寸精确的标准打印件，确认后余额支付直接打印。
      </p>
    </div>

    <Alert class="mb-5">
      <ShieldCheck class="size-4" aria-hidden="true" />
      <AlertDescription>{{ CERT_PRIVACY_NOTE }}</AlertDescription>
    </Alert>

    <Alert v-if="loadError" variant="destructive" class="mb-5">
      <CircleAlert class="size-4" aria-hidden="true" />
      <AlertTitle>证照功能列表加载失败</AlertTitle>
      <AlertDescription>
        <Button size="sm" variant="outline" class="mt-2 h-8" @click="load">重试</Button>
      </AlertDescription>
    </Alert>

    <div class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
      <!-- 静态卡：图文打印（现有主打印功能）排首位；两页合一（doc2up）已随证照模板
           接口驱动（cert_templates 登记行），卡片显隐由后台「证件照管理」启停控制。 -->
      <PortalCard
        icon="printer"
        title="图文打印"
        desc="上传 PDF / Office / 图片，多文件合并打印"
        theme="blue"
        price-text="按页计价"
        to="/"
      />

      <template v-if="loading">
        <Skeleton v-for="n in 3" :key="n" class="h-32 rounded-xl" />
      </template>
      <template v-else>
        <template v-for="template in templates" :key="template.code">
          <PortalCard
            v-if="certModuleRoute(template.code)"
            :icon="template.card?.icon"
            :title="template.name"
            :desc="template.card?.desc"
            :theme="template.card?.theme"
            :price-text="priceTextOf(template)"
            :to="certModuleRoute(template.code)"
          />
          <PortalCard
            v-else
            :icon="template.card?.icon"
            :title="template.name"
            :desc="(template.card?.desc || '') + '（页面暂未开放）'"
            :theme="template.card?.theme"
            :price-text="priceTextOf(template)"
            @click="onUnavailableCard"
          />
        </template>
      </template>
    </div>
  </div>
</template>
