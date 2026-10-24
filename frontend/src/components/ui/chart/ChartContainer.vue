<script>
import { cn } from "@/lib/utils";
import ChartStyle from "./ChartStyle.vue";
</script>

<script setup>
// 修复：CLI 的 JS 转换产物丢失了这些 import（未定义标识符在构建期不报错，
// 运行时 setup 抛 ReferenceError 导致整个图表子树渲染失败、页面空白）。
import { computed, toRefs, useId } from "vue";
import { provideChartContext } from "./index.js";

const props = defineProps({
  id: { type: null, required: false },
  class: { type: null, required: false },
  config: { type: null, required: true },
  cursor: { type: Boolean, required: false },
});

defineSlots();

const { config } = toRefs(props);
const uniqueId = useId();
const chartId = computed(
  () => `chart-${props.id || uniqueId.replace(/:/g, "")}`,
);

provideChartContext({
  id: uniqueId,
  config,
});
</script>

<template>
  <div
    data-slot="chart"
    :data-chart="chartId"
    :class="
      cn(
        `cn-chart [&_.tick_text]:!fill-muted-foreground [&_.tick_line]:!stroke-border/50 [&_.recharts-curve.recharts-tooltip-cursor]:stroke-border [&_.recharts-polar-grid_[stroke='#ccc']]:stroke-border [&_.recharts-radial-bar-background-sector]:fill-muted [&_.recharts-rectangle.recharts-tooltip-cursor]:fill-muted [&_.recharts-reference-line_[stroke='#ccc']]:stroke-border flex flex-col aspect-video justify-center text-xs [&_.recharts-dot[stroke='#fff']]:stroke-transparent [&_.recharts-layer]:outline-hidden [&_.recharts-sector]:outline-hidden [&_.recharts-sector[stroke='#fff']]:stroke-transparent [&_.recharts-surface]:outline-hidden [&_[data-vis-xy-container]]:h-full [&_[data-vis-single-container]]:h-full h-full [&_[data-vis-xy-container]]:w-full [&_[data-vis-single-container]]:w-full w-full `,
        props.class,
      )
    "
    :style="{
      '--vis-tooltip-padding': '0px',
      '--vis-tooltip-background-color': 'transparent',
      '--vis-tooltip-border-color': 'transparent',
      '--vis-tooltip-text-color': 'none',
      '--vis-tooltip-shadow-color': 'none',
      '--vis-tooltip-backdrop-filter': 'none',
      '--vis-crosshair-circle-stroke-color': '#0000',
      '--vis-crosshair-line-stroke-width': cursor ? '1px' : '0px',
      '--vis-font-family': 'var(--font-sans)',
    }"
  >
    <slot :id="uniqueId" :config="config" />
    <ChartStyle :id="chartId" />
  </div>
</template>
