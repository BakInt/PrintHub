<script setup>
// 四点手动裁剪弹层（SVG，无第三方裁剪库）：自动识别失败时的体验下限保障。
// 坐标全部归一化 0–1，提交顺序 TL,TR,BR,BL（与后端 render.perspective_crop 约定一致）。
// 交互：在画面任意处按下即吸附最近的角点并拖动（触控友好），角点圆仅作视觉指示。
import { ref, watch } from 'vue'
import { Crop } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const props = defineProps({
  open: { type: Boolean, default: false },
  imageSrc: { type: String, default: '' },
  slotLabel: { type: String, default: '' },
})

const emit = defineEmits(['update:open', 'save', 'cancel'])

const DEFAULT_POINTS = [
  [0.1, 0.1],
  [0.9, 0.1],
  [0.9, 0.9],
  [0.1, 0.9],
]
// 就近吸附阈值（归一化距离）：按屏幕短边换算后约 48px 的触控容差。
const SNAP_THRESHOLD = 0.12

const points = ref(DEFAULT_POINTS.map((p) => [...p]))
const stageRef = ref(null)
const dragIndex = ref(-1)

watch(
  () => props.open,
  (open) => {
    if (open) points.value = DEFAULT_POINTS.map((p) => [...p])
  },
)

function pointerFromEvent(event) {
  const rect = stageRef.value?.getBoundingClientRect()
  if (!rect) return null
  const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
  const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
  return [x, y]
}

function onStageDown(event) {
  const position = pointerFromEvent(event)
  if (!position) return
  let best = -1
  let bestDistance = Number.POSITIVE_INFINITY
  points.value.forEach((point, index) => {
    const distance = Math.hypot(point[0] - position[0], point[1] - position[1])
    if (distance < bestDistance) {
      bestDistance = distance
      best = index
    }
  })
  if (best >= 0 && bestDistance <= SNAP_THRESHOLD) {
    dragIndex.value = best
    points.value[best] = position
    event.target.setPointerCapture?.(event.pointerId)
    event.preventDefault()
  }
}

function onStageMove(event) {
  if (dragIndex.value < 0) return
  const position = pointerFromEvent(event)
  if (position) points.value[dragIndex.value] = position
}

function onStageUp() {
  dragIndex.value = -1
}

function save() {
  emit('save', points.value.map((p) => [Number(p[0].toFixed(4)), Number(p[1].toFixed(4))]))
  emit('update:open', false)
}

function cancel() {
  emit('cancel')
  emit('update:open', false)
}

const polygonPoints = () => points.value.map((p) => `${p[0] * 100},${p[1] * 100}`).join(' ')
const activePoint = (index) => dragIndex.value === index
</script>

<template>
  <Dialog :open="open" @update:open="(value) => emit('update:open', value)">
    <DialogContent class="max-w-md">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <Crop class="size-4 text-primary" aria-hidden="true" />
          手动框选{{ slotLabel }}
        </DialogTitle>
        <DialogDescription>
          按住并拖动四个角点，使边框紧贴证件边缘（四角完整），然后点击「确认裁剪」。
        </DialogDescription>
      </DialogHeader>

      <div
        ref="stageRef"
        class="relative cursor-crosshair touch-none select-none overflow-hidden rounded-lg border bg-muted/40"
        @pointerdown="onStageDown"
        @pointermove="onStageMove"
        @pointerup="onStageUp"
        @pointercancel="onStageUp"
      >
        <img :src="imageSrc" :alt="slotLabel" class="pointer-events-none block w-full" draggable="false" />
        <svg
          class="pointer-events-none absolute inset-0 h-full w-full"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <polygon
            :points="polygonPoints()"
            fill="rgba(0,0,0,0)"
            stroke="currentColor"
            class="text-primary"
            vector-effect="non-scaling-stroke"
            stroke-width="1.5"
          />
          <circle
            v-for="(point, index) in points"
            :key="index"
            :cx="point[0] * 100"
            :cy="point[1] * 100"
            :r="activePoint(index) ? 2.4 : 1.8"
            class="fill-background stroke-primary"
            vector-effect="non-scaling-stroke"
            stroke-width="1.5"
          />
        </svg>
      </div>

      <DialogFooter class="gap-2 sm:gap-0">
        <Button variant="outline" class="h-10" @click="cancel">取消</Button>
        <Button class="h-10" @click="save">确认裁剪</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
