<template>
  <!-- ICP 备案条：仅当后台「站点设置」填写了备案号才渲染（留空 = 全站不显示）。
       非固定定位、随内容排在页尾，居中小字次要色，亮/暗主题走 CSS 变量；
       只显示备案号本身，点击跳转工信部备案网站（新窗口）。 -->
  <footer v-if="site.icpNumber" class="flex justify-center py-4">
    <a
      href="https://beian.miit.gov.cn/"
      target="_blank"
      rel="noopener noreferrer"
      class="text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
    >{{ site.icpNumber }}</a>
  </footer>
</template>

<script setup>
import { useSiteStore } from '@/stores/site'

const site = useSiteStore()
</script>
