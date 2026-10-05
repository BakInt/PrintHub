<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ClipboardList, CreditCard, FileText, RefreshCw, XCircle } from 'lucide-vue-next'

import { request } from '../api/client'
import { useThemeStore } from '../stores/theme'

// 后台「运营概览」页的「每日数据统计」卡片。
// 图表用内联 SVG 手绘（项目没有引入任何图表库，Docker 构建走 `pnpm install --frozen-lockfile`，
// 新增依赖会同时增加镜像体积与锁文件风险）；颜色全部走主题变量，亮/暗与手机端配色自动跟随。
const theme = useThemeStore()

const RANGE_OPTIONS = [
  { days: 7, label: '近 7 天' },
  { days: 30, label: '近 30 天' }
]

const TAB_OPTIONS = [
  { key: 'orders', label: '订单趋势', icon: ClipboardList },
  { key: 'revenue', label: '收入趋势', icon: CreditCard },
  { key: 'failures', label: '打印失败分布', icon: XCircle }
]

// 图表几何参数（单位：SVG 用户坐标 = CSS 像素，见 chartWidth 的实测逻辑）。
const TICK_COUNT = 4
const AXIS_LEFT = 46
const AXIS_RIGHT = 50
const PAD_TOP = 14
const PAD_BOTTOM = 30
const MIN_CHART_WIDTH = 220

// 每个 Tab 的图表构成：柱状图走左轴、折线图走右轴。
// 「订单趋势」刻意与需求示例保持一致（订单量柱 + 收入线），提示框同时给出「订单量 / 收入」。
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
// 注意「不要新增依赖」是硬约束，所以这里手写一个够用的 nice-number 算法。
function axisMax(rawMax, axis) {
  const floorValue = axis === 'count' ? TICK_COUNT : 1
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
const hoverIndex = ref(-1)

// 图例的显示/隐藏状态按「Tab + 数据系列」记录，切换 Tab 后再切回来仍保留用户选择。
const hiddenSeries = reactive({})

const chartWrap = ref(null)
const chartWidth = ref(720)

let resizeObserver = null

const items = computed(() => stats.value?.items || [])
const chartSpec = computed(() => CHART_SPECS[activeTab.value] || CHART_SPECS.orders)
const chartSeries = computed(() => [chartSpec.value.bar, chartSpec.value.line])
const chartHeight = computed(() => (theme.isMobile ? 216 : 264))

const hasData = computed(() =>
  items.value.some(
    (item) => (Number(item.orders) || 0) > 0 || (Number(item.revenue) || 0) > 0 || (Number(item.failed) || 0) > 0
  )
)

const timezoneTitle = computed(() =>
  stats.value?.timezone ? `按服务器本地时区 ${stats.value.timezone} 统计` : '按服务器本地时区统计'
)

const ariaLabel = computed(() => {
  const label = TAB_OPTIONS.find((option) => option.key === activeTab.value)?.label || ''
  return `每日数据统计：${label}（近 ${rangeDays.value} 天）`
})

function seriesVisibleKey(key) {
  return `${activeTab.value}.${key}`
}

function isSeriesVisible(key) {
  return !hiddenSeries[seriesVisibleKey(key)]
}

function toggleSeries(key) {
  const scoped = seriesVisibleKey(key)
  hiddenSeries[scoped] = !hiddenSeries[scoped]
  hoverIndex.value = -1
}

function selectTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  hoverIndex.value = -1
}

const visibleSeries = computed(() => chartSeries.value.filter((series) => isSeriesVisible(series.key)))
const hasVisibleSeries = computed(() => visibleSeries.value.length > 0)

// 标签抽稀：按可用宽度算出最小间隔，保证「今天」始终可见且邻近标签不重叠。
const labelIndexes = computed(() => {
  const count = items.value.length
  if (!count) return []
  const available = Math.max(chartWidth.value - AXIS_LEFT - AXIS_RIGHT, 120)
  const perLabel = theme.isMobile ? 46 : 58
  const step = Math.max(1, Math.ceil(count / Math.max(1, Math.floor(available / perLabel))))
  const indexes = []
  for (let index = 0; index < count; index += step) indexes.push(index)
  const last = count - 1
  if (indexes[indexes.length - 1] !== last) {
    if (last - indexes[indexes.length - 1] < step / 2) indexes.pop()
    indexes.push(last)
  }
  return indexes
})

const layout = computed(() => {
  const data = items.value
  const spec = chartSpec.value
  const width = Math.max(chartWidth.value, MIN_CHART_WIDTH)
  const height = chartHeight.value
  const plotWidth = Math.max(width - AXIS_LEFT - AXIS_RIGHT, 10)
  const plotHeight = Math.max(height - PAD_TOP - PAD_BOTTOM, 10)
  const band = plotWidth / Math.max(data.length, 1)
  const baseline = PAD_TOP + plotHeight

  const barShown = isSeriesVisible(spec.bar.key)
  const lineShown = isSeriesVisible(spec.line.key)
  const barMax = axisMax(barShown ? Math.max(0, ...data.map((item) => Number(item[spec.bar.key]) || 0)) : 0, spec.bar.axis)
  const lineMax = axisMax(lineShown ? Math.max(0, ...data.map((item) => Number(item[spec.line.key]) || 0)) : 0, spec.line.axis)

  const xFor = (index) => AXIS_LEFT + band * (index + 0.5)
  const yFor = (value, max) => baseline - (Math.max(0, Number(value) || 0) / max) * plotHeight

  const ticks = Array.from({ length: TICK_COUNT + 1 }, (_, index) => {
    const ratio = index / TICK_COUNT
    return { ratio, value: barMax * ratio, lineValue: lineMax * ratio, y: baseline - ratio * plotHeight }
  })

  const barWidth = Math.max(4, Math.min(band * (data.length > 14 ? 0.62 : 0.46), 46))

  const bars = barShown
    ? data.map((item, index) => {
        const value = Number(item[spec.bar.key]) || 0
        const y = yFor(value, barMax)
        return { index, value, x: xFor(index) - barWidth / 2, y, width: barWidth, height: Math.max(baseline - y, 0) }
      })
    : []

  const linePoints = lineShown
    ? data.map((item, index) => ({ index, value: Number(item[spec.line.key]) || 0, x: xFor(index), y: yFor(item[spec.line.key], lineMax) }))
    : []
  const linePath = linePoints.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')

  return {
    width,
    height,
    padLeft: AXIS_LEFT,
    padRight: AXIS_RIGHT,
    padTop: PAD_TOP,
    plotWidth,
    plotHeight,
    baseline,
    band,
    ticks,
    bars,
    linePoints,
    linePath,
    labelIndexes: labelIndexes.value,
    xFor,
    axisCenterY: PAD_TOP + plotHeight / 2
  }
})

const hoverItem = computed(() => (hoverIndex.value >= 0 ? items.value[hoverIndex.value] || null : null))
const hoverX = computed(() => (hoverItem.value ? layout.value.xFor(hoverIndex.value) : 0))

const tooltipStyle = computed(() => {
  const width = layout.value.width
  const half = 96
  const left = Math.min(Math.max(hoverX.value, half), Math.max(width - half, half))
  return { left: `${left}px` }
})

async function loadStats() {
  loading.value = true
  errorMessage.value = ''
  hoverIndex.value = -1
  try {
    stats.value = await request(`/api/admin/daily-stats?days=${rangeDays.value}`)
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

onMounted(() => {
  // 先量一次，避免首屏用默认宽度画完再跳一下；随后交给 ResizeObserver 跟随侧边栏/窗口变化。
  if (chartWrap.value?.clientWidth) chartWidth.value = chartWrap.value.clientWidth
  if (typeof ResizeObserver !== 'undefined' && chartWrap.value) {
    resizeObserver = new ResizeObserver((entries) => {
      const width = Math.round(entries[0]?.contentRect?.width || 0)
      if (width > 0) chartWidth.value = width
    })
    resizeObserver.observe(chartWrap.value)
  }
  loadStats()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <section class="panel daily-stats-card">
    <div class="daily-stats-head">
      <h2 class="daily-stats-title">每日数据统计</h2>
      <div class="segmented-control daily-stats-range">
        <button
          v-for="option in RANGE_OPTIONS"
          :key="option.days"
          type="button"
          :class="{ selected: rangeDays === option.days }"
          :disabled="loading"
          @click="selectRange(option.days)"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <div class="daily-stats-tabs">
      <button
        v-for="option in TAB_OPTIONS"
        :key="option.key"
        type="button"
        :class="['daily-stats-tab', { selected: activeTab === option.key }]"
        @click="selectTab(option.key)"
      >
        <component :is="option.icon" :size="16" />{{ option.label }}
      </button>
    </div>

    <div v-if="errorMessage" class="notice warning">{{ errorMessage }}</div>

    <div ref="chartWrap" class="daily-stats-chart">
      <div v-if="loading" class="daily-stats-loading">
        <RefreshCw :size="18" class="daily-stats-spin" />
        <span>数据加载中…</span>
      </div>

      <div v-if="!loading && !hasData" class="daily-stats-empty">
        <FileText :size="26" />
        <strong>所选时间范围内暂无数据</strong>
        <span>该区间还没有订单记录，换个时间范围再看看</span>
      </div>

      <template v-else>
        <div class="daily-stats-legend">
          <button
            v-for="series in chartSeries"
            :key="series.key"
            type="button"
            :class="['daily-stats-legend-item', { off: !isSeriesVisible(series.key) }]"
            :title="`点击${isSeriesVisible(series.key) ? '隐藏' : '显示'}「${series.label}」`"
            @click="toggleSeries(series.key)"
          >
            <i :class="['daily-stats-dot', series.kind]"></i>{{ series.label }}
          </button>
        </div>

        <div class="daily-stats-plot">
          <svg
            class="daily-stats-svg"
            :viewBox="`0 0 ${layout.width} ${layout.height}`"
            :style="{ height: `${layout.height}px` }"
            role="img"
            :aria-label="ariaLabel"
            @mouseleave="hoverIndex = -1"
          >
            <g class="daily-stats-grid">
              <line
                v-for="tick in layout.ticks"
                :key="`grid-${tick.ratio}`"
                :x1="layout.padLeft"
                :x2="layout.width - layout.padRight"
                :y1="tick.y"
                :y2="tick.y"
              />
            </g>

            <g v-if="isSeriesVisible(chartSpec.bar.key)" class="daily-stats-axis">
              <text
                v-for="tick in layout.ticks"
                :key="`left-${tick.ratio}`"
                :x="layout.padLeft - 8"
                :y="tick.y + 4"
                text-anchor="end"
              >
                {{ formatTick(tick.value, chartSpec.bar.axis) }}
              </text>
              <text
                class="daily-stats-axis-title"
                :x="-layout.axisCenterY"
                y="12"
                :transform="`rotate(-90)`"
                text-anchor="middle"
                dominant-baseline="middle"
              >
                {{ AXIS_TITLES[chartSpec.bar.axis] }}
              </text>
            </g>

            <g v-if="isSeriesVisible(chartSpec.line.key)" class="daily-stats-axis">
              <text
                v-for="tick in layout.ticks"
                :key="`right-${tick.ratio}`"
                :x="layout.width - layout.padRight + 8"
                :y="tick.y + 4"
                text-anchor="start"
              >
                {{ formatTick(tick.lineValue, chartSpec.line.axis) }}
              </text>
              <text
                class="daily-stats-axis-title"
                :x="layout.axisCenterY"
                :y="-(layout.width - 12)"
                :transform="`rotate(90)`"
                text-anchor="middle"
                dominant-baseline="middle"
              >
                {{ AXIS_TITLES[chartSpec.line.axis] }}
              </text>
            </g>

            <g class="daily-stats-bars">
              <rect
                v-for="bar in layout.bars"
                :key="`bar-${bar.index}`"
                :x="bar.x"
                :y="bar.y"
                :width="bar.width"
                :height="bar.height"
                rx="2"
              />
            </g>

            <g v-if="layout.linePoints.length" class="daily-stats-line">
              <path :d="layout.linePath" />
              <circle v-for="point in layout.linePoints" :key="`point-${point.index}`" :cx="point.x" :cy="point.y" r="3" />
            </g>

            <line
              v-if="hoverItem"
              class="daily-stats-guide"
              :x1="hoverX"
              :x2="hoverX"
              :y1="layout.padTop"
              :y2="layout.baseline"
            />

            <text
              v-if="!hasVisibleSeries"
              class="daily-stats-hint"
              :x="layout.padLeft + layout.plotWidth / 2"
              :y="layout.padTop + layout.plotHeight / 2"
              text-anchor="middle"
            >
              已隐藏全部数据系列，点击上方图例恢复
            </text>

            <text
              v-for="index in layout.labelIndexes"
              :key="`xlabel-${index}`"
              class="daily-stats-xlabel"
              :x="layout.xFor(index)"
              :y="layout.baseline + 18"
              text-anchor="middle"
            >
              {{ items[index]?.label }}
            </text>

            <g class="daily-stats-hits">
              <rect
                v-for="(item, index) in items"
                :key="`hit-${item.date}`"
                :x="layout.padLeft + layout.band * index"
                :y="layout.padTop"
                :width="layout.band"
                :height="layout.plotHeight"
                @mouseenter="hoverIndex = index"
                @click="hoverIndex = index"
              />
            </g>
          </svg>

          <div v-if="hoverItem && hasVisibleSeries" class="daily-stats-tooltip" :style="tooltipStyle">
            <strong>{{ hoverItem.label }}</strong>
            <span v-for="series in visibleSeries" :key="`tip-${series.key}`">
              <i :class="['daily-stats-dot', series.kind]"></i>{{ series.label }}：{{ series.format(hoverItem[series.key]) }}
            </span>
          </div>
        </div>
      </template>
    </div>

    <p class="daily-stats-foot" :title="timezoneTitle">按本地时区统计每日订单与收入变化</p>
  </section>
</template>
