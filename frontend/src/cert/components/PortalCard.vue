<script setup>
// 门户功能卡：图标 + 功能名 + 一句话说明 + 价格提示。配色全部来自 CSS 变量组合（constants.js）。
import { Badge } from '@/components/ui/badge'
import { certIcon, certThemeClass } from '../constants'

defineProps({
  icon: { type: String, default: '' },
  title: { type: String, required: true },
  desc: { type: String, default: '' },
  theme: { type: String, default: 'blue' },
  priceText: { type: String, default: '' },
  to: { type: String, default: '' },
})
</script>

<template>
  <component :is="to ? 'RouterLink' : 'div'" :to="to || undefined" class="group block">
    <div
      class="flex h-full min-h-28 flex-col gap-2.5 rounded-xl border bg-card p-4 transition-colors"
      :class="to ? 'hover:border-primary/40 hover:bg-accent/40' : 'opacity-70'"
    >
      <span
        class="grid size-10 shrink-0 place-items-center rounded-lg border"
        :class="certThemeClass(theme)"
        aria-hidden="true"
      >
        <component :is="certIcon(icon)" class="size-5" />
      </span>
      <div class="flex items-center justify-between gap-2">
        <span class="text-sm font-bold">{{ title }}</span>
        <Badge v-if="priceText" variant="secondary" class="shrink-0 text-[11px]">{{ priceText }}</Badge>
      </div>
      <p class="text-xs leading-relaxed text-muted-foreground">{{ desc }}</p>
    </div>
  </component>
</template>
