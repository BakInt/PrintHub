<script setup>
// 槽位上传卡：拍照（手机直调相机）/ 相册选择 → 回显缩略图 → 可重拍。
// 纯声明组件：File 对象通过 v-model 交给骨架，不发起任何请求。
import { computed, ref, watch } from 'vue'
import { Camera, ImagePlus, RotateCcw } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  slotKey: { type: String, required: true },
  label: { type: String, required: true },
  tip: { type: String, default: '' },
  modelValue: { type: File, default: null },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const cameraInput = ref(null)
const galleryInput = ref(null)

const previewUrl = ref('')

watch(
  () => props.modelValue,
  (file) => {
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = file ? URL.createObjectURL(file) : ''
  },
)

const ready = computed(() => Boolean(props.modelValue))

function pick(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file) emit('update:modelValue', file)
}

function retake() {
  emit('update:modelValue', null)
}
</script>

<template>
  <div
    class="flex flex-col gap-2.5 rounded-xl border p-3.5 transition-colors"
    :class="ready ? 'border-primary/40 bg-card' : 'border-dashed border-border bg-card/50'"
  >
    <div class="flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2">
        <span class="truncate text-sm font-semibold">{{ label }}</span>
        <Badge v-if="ready" variant="secondary" class="shrink-0">已选择</Badge>
        <Badge v-else variant="outline" class="shrink-0 text-muted-foreground">待上传</Badge>
      </div>
    </div>

    <div v-if="ready" class="relative overflow-hidden rounded-lg border bg-muted/40">
      <img :src="previewUrl" :alt="label" class="max-h-56 w-full object-contain" />
    </div>
    <div
      v-else
      class="grid h-28 place-items-center rounded-lg border border-dashed bg-muted/30 text-muted-foreground"
    >
      <div class="flex flex-col items-center gap-1 text-xs">
        <ImagePlus class="size-5" aria-hidden="true" />
        <span>上传{{ label }}照片</span>
      </div>
    </div>

    <p v-if="tip" class="text-xs leading-relaxed text-muted-foreground">{{ tip }}</p>

    <div class="flex flex-wrap gap-2">
      <Button v-if="!ready" size="sm" variant="secondary" class="h-9" :disabled="disabled" @click="cameraInput?.click()">
        <Camera class="size-4" aria-hidden="true" />拍照
      </Button>
      <Button v-if="!ready" size="sm" variant="secondary" class="h-9" :disabled="disabled" @click="galleryInput?.click()">
        <ImagePlus class="size-4" aria-hidden="true" />相册选择
      </Button>
      <Button v-if="ready" size="sm" variant="outline" class="h-9" :disabled="disabled" @click="retake()">
        <RotateCcw class="size-4" aria-hidden="true" />重拍
      </Button>
    </div>

    <input
      ref="cameraInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      capture="environment"
      class="hidden"
      @change="pick"
    />
    <input
      ref="galleryInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      class="hidden"
      @change="pick"
    />
  </div>
</template>
