<script setup>
// 户口本打印（独立模块页）：户主页 + 个人页两个槽位排入同一页 A4（上下排布、
// 居中同列，与身份证正反面同页同理）；行为全部由 ModuleShell 编排，自动裁切矫正。
import ModuleShell from './ModuleShell.vue'

const slots = [
  {
    key: 'holder',
    label: '户口本户主页',
    tip: '页面平整、避免装订阴影、字迹清晰',
  },
  {
    key: 'personal',
    label: '户口本个人页',
    tip: '页面平整、避免装订阴影、字迹清晰',
  },
]

const moduleCopy = {
  title: '户口本打印',
  subtitle: '户主页与个人页自动排入同一页 A4',
  description: '拍摄户口本户主页与个人页，系统自动裁切矫正后上下排入一页 A4 打印（户主页在上、个人页在下，与身份证正反面版式一致，可沿浅灰裁剪框裁开）。',
}
</script>

<template>
  <ModuleShell template-code="hukou" :slots="slots" :module-copy="moduleCopy" :defaults="{ copies: 1 }" />
</template>
