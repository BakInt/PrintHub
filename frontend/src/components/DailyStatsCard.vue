<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { h, render } from 'vue'
import { ChartCrosshair, ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { VisAxis, VisLine, VisStackedBar, VisXYContainer } from '@unovis/vue'
import { CircleCheck, ClipboardList, CreditCard, FileText, RefreshCw, TriangleAlert, XCircle } from 'lucide-vue-next'

import { request } from '@/api/client'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

// 后台「运营概览」页的「每日数据统计」卡片。
// 图表使用 shadcn-vue 官方 Chart 组件（底层 Unovis），主题色全部走
// CSS 变量（--chart-1/--chart-2），亮/暗主题自动跟随；
// 每个 Tab 是「柱状(左轴) + 折线(右轴)」双轴组合。
// 「订单趋势」刻意与需求示例保持一致（订单量柱 + 收入线），提示框同时给出「订单量 / 收入」。
const RANGE_OPTIONS = [
  { days: 7, label: '近 7 天' },
  { days: 30, label: '近 30 天' }
]

const TAB_OPTIONS = [
  { key: 'orders', label: '订单趋势', icon: ClipboardList },
  { key: 'revenue', label: '收入趋势', icon: CreditCard },
  { key: 'failures', label: '打印失败分布', icon: XCircle }
]

const CHART_SPECS = {
  orders: {
    bar: { key: 'orders', label: '订单量', axis: 'count', kind: 'bar', format: (value) => `${Number(value) || 0}` },
    line: { key: 'revenue', label: '收入', axis: 'money', kind: 'line', format: (value) => formatMoney(value) }
  },
  revenue: {
    bar: { key: 'revenue', label: '收入', axis: 'money', kind: 'bar', format: (value) => formatMoney(value) },
    line: { key: 'orders', label: '订单量', axis: 'count', kind: 'line', format: (value) => `${Number(value) || 0}` }
  },
  failures: {
    bar: { key: 'failed', label: '打印失败', axis: 'count', kind: 'bar', format: (value) => `${Number(value) || 0}` },
    line: { key: 'failure_rate', label: '失败率', axis: 'percent', kind: 'line', format: (value) => `${(Number(value) || 0).toFixed(1)}%` }
  }
}

const AXIS_TITLES = { count: '数量', money: '收入(¥)', percent: '失败率(%)' }

function formatMoney(value) {
  return `¥${(Number(value) || 0).toFixed(2)}`
}

function niceMax(value) {
  if (!Number.isFinite(value) || value <= 0) return 0
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const normalized = value / magnitude
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10
  return step * magnitude
}

// 轴最大值：留 8% 顶部余量，柱顶不贴边；全 0 时给一个最小刻度，避免标签全挤在 0。
function axisMax(rawMax, axis) {
  const floorValue = axis === 'count' ? 4 : 1
  const safe = Number.isFinite(rawMax) && rawMax > 0 ? rawMax : 0
  if (safe <= 0) return floorValue
  return Math.max(niceMax(safe * 1.08), floorValue)
}

function formatTick(value, axis) {
  if (axis === 'percent') return `${Math.round(value)}%`
  if (axis === 'money' && value >= 1000) return `${Math.round(value / 100) / 10}k`
  return `${Math.round(value)}`
}

const rangeDays = ref(7)
const activeTab = ref('orders')
const stats = ref(null)
const loading = ref(false)
const errorMessage = ref('')

// 图例的显示/隐藏状态按「Tab + 数据系列」记录，切换 Tab 后再切回来仍保留用户选择。
const hiddenSeries = reactive({})

const items = computed(() => stats.value?.items || [])
const chartSpec = computed(() => CHART_SPECS[activeTab.value] || CHART_SPECS.orders)
const chartSeries = computed(() => [chartSpec.value.bar, chartSpec.value.line])

const hasData = computed(() =>
  items.value.some(
    (item) => (Number(item.orders) || 0) > 0 || (Number(item.revenue) || 0) > 0 || (Number(item.failed) || 0) > 0
  )
)

const timezoneTitle = computed(() =>
  stats.value?.timezone ? `按服务器本地时区 ${stats.value.timezone} 统计` : '按服务器本地时区统计'
)

function seriesVisibleKey(key) {
  return `${activeTab.value}.${key}`
}

function isSeriesVisible(key) {
  return !hiddenSeries[seriesVisibleKey(key)]
}

function toggleSeries(key) {
  const scoped = seriesVisibleKey(key)
  hiddenSeries[scoped] = !hiddenSeries[scoped]
}

function selectTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
}

const visibleSeries = computed(() => chartSeries.value.filter((series) => isSeriesVisible(series.key)))
const hasVisibleSeries = computed(() => visibleSeries.value.length > 0)
const showBar = computed(() => isSeriesVisible(chartSpec.value.bar.key))
const showLine = computed(() => isSeriesVisible(chartSpec.value.line.key))

// shadcn 图表的系列配置：颜色引用主题 CSS 变量，亮/暗自动跟随（ChartStyle 会生成
// `[data-chart] { --color-<key> }` 与 `.dark` 覆盖）。
const chartConfig = computed(() => ({
  [chartSpec.value.bar.key]: { label: chartSpec.value.bar.label, color: 'var(--chart-1)' },
  [chartSpec.value.line.key]: { label: chartSpec.value.line.label, color: 'var(--chart-2)' }
}))

// 双轴量程：柱与线分别按各自可见性计算，与手写版一致的 nice-number 留白逻辑。
const barDomain = computed(() => {
  if (!showBar.value) return [0, 1]
  const rawMax = Math.max(0, ...items.value.map((item) => Number(item[chartSpec.value.bar.key]) || 0))
  return [0, axisMax(rawMax, chartSpec.value.bar.axis)]
})
const lineDomain = computed(() => {
  if (!showLine.value) return [0, 1]
  const rawMax = Math.max(0, ...items.value.map((item) => Number(item[chartSpec.value.line.key]) || 0))
  return [0, axisMax(rawMax, chartSpec.value.line.axis)]
})

// x 轴刻度：日期过密时由 Unovis 均匀抽稀；标签从数据里取。
const xNumTicks = computed(() => Math.min(Math.max(items.value.length, 2), items.value.length > 14 ? 6 : items.value.length))
function xTickFormat(value) {
  const item = items.value[Math.round(Number(value))]
  return item?.label ?? ''
}

// 提示框：把悬浮的日期 + 各可见系列（已格式化）交给官方 ChartTooltipContent 渲染，
// 并按内容缓存 HTML，避免鼠标滑动时反复挂载。
const tooltipCache = new Map()
function crosshairTemplate(datum, x) {
  const data = 'data' in datum ? datum.data : datum
  const index = Math.round(Number(x))
  const item = items.value[index]
  if (!item || !hasVisibleSeries.value) return ''
  const payload = {}
  for (const series of visibleSeries.value) {
    payload[series.key] = series.format(item[series.key])
  }
  const cacheKey = JSON.stringify([activeTab.value, rangeDays.value, item.label, Object.keys(payload)])
  const cached = tooltipCache.get(cacheKey)
  if (cached) return cached
  const vnode = h(ChartTooltipContent, {
    payload,
    config: chartConfig.value,
    x,
    labelFormatter: (value) => items.value[Math.round(Number(value))]?.label ?? ''
  })
  const div = document.createElement('div')
  render(vnode, div)
  tooltipCache.set(cacheKey, div.innerHTML)
  return div.innerHTML
}

// 图例点颜色（跟随系列色）
const legendDotStyle = (series) => ({
  background: series.kind === 'bar' ? 'var(--chart-1)' : 'var(--chart-2)'
})

async function loadStats() {
  loading.value = true
  errorMessage.value = ''
  try {
    stats.value = await request(`/api/admin/daily-stats?days=${rangeDays.value}`)
    tooltipCache.clear()
  } catch (error) {
    errorMessage.value = error?.message || '每日数据统计加载失败'
  } finally {
    loading.value = false
  }
}

function selectRange(days) {
  if (days === rangeDays.value || loading.value) return
  rangeDays.value = days
  loadStats()
}

onMounted(loadStats)
</script>

<template>
  <Card class="gap-2.5 py-4">
    <CardHeader class="flex-row flex-wrap items-center justify-between gap-3 pb-0">
      <CardTitle class="font-display text-lg">每日数据统计</CardTitle>
      <!-- 两组 Tab 统一规格：h-9 / text-sm / rounded-lg，选中态为 muted 轨道上的主卡片色胶囊（全站统一样式） -->
      <Tabs :model-value="String(rangeDays)" @update:model-value="(value) => selectRange(Number(value))">
        <TabsList class="h-9!">
          <TabsTrigger v-for="option in RANGE_OPTIONS" :key="option.days" :value="String(option.days)" :disabled="loading" class="px-4 text-sm">
            {{ option.label }}
          </TabsTrigger>
        </TabsList>
      </Tabs>
    </CardHeader>

    <CardContent class="grid gap-2.5">
      <!-- 维度切换：与时间范围 Tab 同规格；窄屏可横向滑动 -->
      <div class="-mx-1 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" style="overscroll-behavior-x: contain">
        <Tabs :model-value="activeTab" @update:model-value="selectTab">
          <TabsList class="h-9!">
            <TabsTrigger v-for="option in TAB_OPTIONS" :key="option.key" :value="option.key" class="gap-1.5 px-3.5 text-sm">
              <component :is="option.icon" class="size-4" />
              {{ option.label }}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <Alert v-if="errorMessage" class="border-warning/30 bg-warning/10 text-warning">
        <TriangleAlert class="size-4" />
        <AlertDescription class="text-warning">{{ errorMessage }}</AlertDescription>
      </Alert>

      <!-- 加载占位 -->
      <div v-if="loading && !stats" class="grid gap-3">
        <Skeleton class="h-4 w-40" />
        <Skeleton class="h-56 w-full rounded-xl" />
        <Skeleton class="h-4 w-64" />
      </div>

      <!-- 空数据占位 -->
      <Empty v-else-if="!loading && !hasData" class="py-8">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileText />
          </EmptyMedia>
          <EmptyTitle>所选时间范围内暂无数据</EmptyTitle>
          <EmptyDescription>该区间还没有订单记录，换个时间范围再看看</EmptyDescription>
        </EmptyHeader>
      </Empty>

      <!-- 图表 -->
      <template v-else>
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-for="series in chartSeries"
            :key="series.key"
            type="button"
            class="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-2 text-[13px] font-medium transition-colors"
            :class="isSeriesVisible(series.key) ? 'text-foreground hover:bg-muted' : 'text-muted-foreground/50 hover:bg-muted'"
            :title="`点击${isSeriesVisible(series.key) ? '隐藏' : '显示'}「${series.label}」`"
            @click="toggleSeries(series.key)"
          >
            <i class="size-2.5 rounded-full" :style="legendDotStyle(series)" aria-hidden="true"></i>
            {{ series.label }}
          </button>
          <Badge v-if="showBar" variant="outline" class="text-[11px] font-normal text-muted-foreground">左轴：{{ AXIS_TITLES[chartSpec.bar.axis] }}</Badge>
          <Badge v-if="showLine" variant="outline" class="text-[11px] font-normal text-muted-foreground">右轴：{{ AXIS_TITLES[chartSpec.line.axis] }}</Badge>
        </div>

        <div class="relative">
          <div v-if="loading" class="absolute inset-0 z-10 grid place-items-center gap-2 rounded-xl bg-background/70 backdrop-blur-sm">
            <Spinner class="size-5 text-primary" />
            <span class="text-[13px] font-semibold text-muted-foreground">数据加载中…</span>
          </div>

          <ChartContainer :config="chartConfig" cursor class="h-52 w-full sm:h-64">
            <VisXYContainer
              :data="items"
              :x-domain="[-0.5, Math.max(items.length - 0.5, 0.5)]"
              :padding="{ top: 8 }"
            >
              <VisStackedBar
                v-if="showBar"
                :x="(_, index) => index"
                :y="(item) => Math.max(0, Number(item[chartSpec.bar.key]) || 0)"
                :color="'var(--chart-1)'"
                :bar-padding="0.25"
                :rounded-top="3"
              />
              <VisLine
                v-if="showLine"
                :x="(_, index) => index"
                :y="(item) => Number(item[chartSpec.line.key]) || 0"
                :color="'var(--chart-2)'"
                :line-width="2"
              />
              <VisAxis
                type="x"
                :num-ticks="xNumTicks"
                :tick-format="xTickFormat"
                :gridline="false"
                :tick-line-width="0"
              />
              <VisAxis
                v-if="showBar"
                type="y"
                position="left"
                :y-domain="barDomain"
                :num-ticks="4"
                :tick-format="(value) => formatTick(value, chartSpec.bar.axis)"
              />
              <VisAxis
                v-if="showLine"
                type="y"
                position="right"
                :y-domain="lineDomain"
                :num-ticks="4"
                :tick-format="(value) => formatTick(value, chartSpec.line.axis)"
              />
              <ChartCrosshair :template="crosshairTemplate" />
              <ChartTooltip />
            </VisXYContainer>
          </ChartContainer>

          <div
            v-if="!hasVisibleSeries"
            class="absolute inset-0 grid place-items-center rounded-xl bg-background/70 text-sm text-muted-foreground backdrop-blur-sm"
          >
            已隐藏全部数据系列，点击上方图例恢复
          </div>
        </div>
      </template>

      <p class="text-xs text-muted-foreground" :title="timezoneTitle">按本地时区统计每日订单与收入变化</p>
    </CardContent>
  </Card>
</template>
