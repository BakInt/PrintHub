<script setup>
// 身份证正反面打印（独立模块页）：声明槽位/文案/默认值，行为全部由 ModuleShell 编排。
import ModuleShell from './ModuleShell.vue'

const slots = [
  {
    key: 'front',
    label: '身份证人像面',
    tip: '证件平放、四角完整、避免手指遮挡与反光',
  },
  {
    key: 'back',
    label: '身份证国徽面',
    tip: '平放深色背景上，避免反光遮挡国徽与文字',
  },
]

const moduleCopy = {
  title: '身份证正反面打印',
  subtitle: '正反面自动排入同一页 A4，1:1 实际尺寸',
  description:
    '拍摄身份证人像面与国徽面，系统自动裁剪矫正后排入一页 A4（85.6×54mm 实际尺寸），打印后沿浅灰裁剪框裁下即为原件尺寸。',
}
</script>

<template>
  <ModuleShell template-code="id_card" :slots="slots" :module-copy="moduleCopy" :defaults="{ copies: 1 }" />
</template>
