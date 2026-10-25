<script setup>
// 模块页公共骨架：编排「槽位上传 → 生成 → 预览 → 下单」。模块页只做声明 + 组合
//（templateCode / slots / moduleCopy / defaults），模块间零引用，差异全部来自声明。
// 骨架负责：模板启停感知（已下架横幅）、登录引导、生成调用与 DETECT_FAILED 分支
//（仅失败槽位弹四点裁剪）、A4 预览、下单面板挂载。
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { ArrowLeft, CircleAlert, FileText, LoaderCircle, LogIn, ShieldCheck } from 'lucide-vue-next'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuthStore } from '@/stores/auth'
import { CERT_PRIVACY_NOTE } from '../constants'
import { fetchCertTemplates, generateCertDoc } from '../api'
import CropOverlay from '../components/CropOverlay.vue'
import CertOrderPanel from '../components/CertOrderPanel.vue'
import SlotUploader from '../components/SlotUploader.vue'

const props = defineProps({
  templateCode: { type: String, required: true },
  slots: { type: Array, required: true },
  moduleCopy: { type: Object, required: true },
  defaults: { type: Object, default: () => ({}) },
})

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const templatesLoading = ref(true)
const template = ref(null)
const templatesError = ref(false)

const slotFiles = reactive({})
const slotQuads = reactive({})
props.slots.forEach((slot) => {
  slotFiles[slot.key] = null
  slotQuads[slot.key] = null
})

const generating = ref(false)
const generated = ref(null)

const cropOpen = ref(false)
const cropSlot = ref('')
const cropQueue = ref([])

const offline = computed(() => !templatesLoading.value && !templatesError.value && !template.value)

function setSlot(key, file) {
  slotFiles[key] = file
  slotQuads[key] = null
  if (generated.value) generated.value = null
}

const loginRedirect = computed(() => ({ path: '/login', query: { redirect: route.fullPath } }))

function requireLogin() {
  if (auth.user) return true
  router.push(loginRedirect.value)
  return false
}

async function loadTemplate() {
  templatesLoading.value = true
  templatesError.value = false
  try {
    const list = await fetchCertTemplates()
    template.value = list.find((item) => item.code === props.templateCode) || null
  } catch {
    templatesError.value = true
  } finally {
    templatesLoading.value = false
  }
}

onMounted(loadTemplate)

function imageSourceOf(key) {
  const file = slotFiles[key]
  return file ? URL.createObjectURL(file) : ''
}

async function generate() {
  if (!requireLogin()) return
  const missing = props.slots.filter((slot) => !slotFiles[slot.key])
  if (missing.length) {
    toast.warning(`请先上传${missing.map((slot) => slot.label).join('、')}`)
    return
  }
  generating.value = true
  try {
    const files = {}
    const quads = {}
    props.slots.forEach((slot) => {
      files[slot.key] = slotFiles[slot.key]
      if (slotQuads[slot.key]) quads[slot.key] = slotQuads[slot.key]
    })
    generated.value = await generateCertDoc({
      templateCode: props.templateCode,
      files,
      quads,
    })
    toast.success('生成成功，请预览并确认打印')
  } catch (error) {
    const detail = error?.data?.detail
    if (detail && typeof detail === 'object' && detail.code === 'DETECT_FAILED') {
      const message = detail.message || '自动识别失败，请手动框选证件边缘'
      toast.warning(message)
      cropQueue.value = (detail.slots || []).filter((key) => key in slotFiles && slotFiles[key])
      if (cropQueue.value.length) openNextCrop()
      return
    }
    toast.error(error?.message || '生成失败，请稍后重试')
  } finally {
    generating.value = false
  }
}

function openNextCrop() {
  cropSlot.value = cropQueue.value[0] || ''
  cropOpen.value = Boolean(cropSlot.value)
}

function onCropSave(quad) {
  if (cropSlot.value) slotQuads[cropSlot.value] = quad
  cropQueue.value = cropQueue.value.filter((key) => key !== cropSlot.value)
  if (cropQueue.value.length) {
    openNextCrop()
    return
  }
  // 全部失败槽位已手动框选 → 自动重试生成（确定性重试：已成功槽位结果不变）。
  cropOpen.value = false
  generate()
}

function onCropCancel() {
  cropQueue.value = []
  cropOpen.value = false
}

const slotLabelOf = (key) => props.slots.find((slot) => slot.key === key)?.label || key
</script>

<template>
  <div class="mx-auto w-full max-w-5xl px-3 py-6 sm:px-6">
    <!-- 页头 -->
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h1 class="font-display text-2xl font-bold tracking-tight sm:text-3xl">{{ moduleCopy.title }}</h1>
        <p class="mt-1 text-sm text-muted-foreground">{{ moduleCopy.subtitle }}</p>
      </div>
      <Button as-child variant="ghost" size="sm" class="h-9 text-muted-foreground">
        <RouterLink to="/cert">
          <ArrowLeft class="size-4" aria-hidden="true" />返回证照门户
        </RouterLink>
      </Button>
    </div>

    <!-- 登录引导（可浏览，生成/下单时再拦截 401 → 登录后回跳本页） -->
    <Alert v-if="!auth.user" class="mb-4">
      <LogIn class="size-4" aria-hidden="true" />
      <AlertTitle>未登录</AlertTitle>
      <AlertDescription class="flex flex-wrap items-center gap-2">
        <span>可以先浏览与准备照片；生成与打印需要登录（使用余额支付）。</span>
        <Button as-child size="sm" variant="outline" class="h-8">
          <RouterLink :to="loginRedirect">去登录</RouterLink>
        </Button>
      </AlertDescription>
    </Alert>

    <!-- 模板加载 / 下架状态 -->
    <div v-if="templatesLoading" class="mb-4 grid gap-3 sm:grid-cols-2">
      <Skeleton v-for="slot in slots" :key="slot.key" class="h-44 rounded-xl" />
    </div>
    <Alert v-else-if="templatesError" variant="destructive" class="mb-4">
      <CircleAlert class="size-4" aria-hidden="true" />
      <AlertTitle>模板信息加载失败</AlertTitle>
      <AlertDescription>
        <Button size="sm" variant="outline" class="mt-2 h-8" @click="loadTemplate">重试</Button>
      </AlertDescription>
    </Alert>
    <Alert v-else-if="offline" variant="destructive" class="mb-4">
      <CircleAlert class="size-4" aria-hidden="true" />
      <AlertTitle>该功能已下架</AlertTitle>
      <AlertDescription>
        <Button as-child size="sm" variant="outline" class="mt-2 h-8">
          <RouterLink to="/cert">返回证照门户</RouterLink>
        </Button>
      </AlertDescription>
    </Alert>

    <template v-else>
      <Alert class="mb-4">
        <ShieldCheck class="size-4" aria-hidden="true" />
        <AlertDescription>{{ moduleCopy.description }}</AlertDescription>
      </Alert>

      <!-- 槽位上传区 -->
      <div class="grid gap-3 sm:grid-cols-2">
        <SlotUploader
          v-for="slot in slots"
          :key="slot.key"
          :slot-key="slot.key"
          :label="slot.label"
          :tip="slot.tip"
          :model-value="slotFiles[slot.key]"
          :disabled="generating"
          @update:model-value="(file) => setSlot(slot.key, file)"
        />
      </div>

      <p class="mt-3 text-xs leading-relaxed text-muted-foreground">{{ CERT_PRIVACY_NOTE }}</p>

      <Button class="mt-4 h-11 w-full max-w-xs text-base font-semibold" :disabled="generating" @click="generate">
        <LoaderCircle v-if="generating" class="size-4 animate-spin" aria-hidden="true" />
        {{ generating ? '正在生成…' : '生成打印件' }}
      </Button>

      <!-- 生成结果：A4 预览 + 下单面板 -->
      <div v-if="generated" class="mt-8 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-base">
              <FileText class="size-4 text-primary" aria-hidden="true" />打印件预览
            </CardTitle>
            <CardDescription>等比缩放预览，实际打印尺寸 1:1（A4 · 300dpi）。</CardDescription>
          </CardHeader>
          <CardContent class="flex flex-col gap-3">
            <iframe
              :src="generated.preview_url"
              title="证照打印件预览"
              class="h-[60vh] w-full rounded-lg border bg-muted/30"
            />
            <Button variant="outline" class="h-9" :disabled="generating" @click="generate">重新生成</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle class="text-base">确认打印</CardTitle>
            <CardDescription>使用账户余额支付，扣费成功后自动派发打印。</CardDescription>
          </CardHeader>
          <CardContent>
            <CertOrderPanel :file-id="generated.file_id" :template="template" :defaults="defaults" />
          </CardContent>
        </Card>
      </div>
    </template>

    <!-- 手动四点裁剪（仅识别失败的槽位依次弹出） -->
    <CropOverlay
      v-model:open="cropOpen"
      :image-src="imageSourceOf(cropSlot)"
      :slot-label="slotLabelOf(cropSlot)"
      @save="onCropSave"
      @cancel="onCropCancel"
    />
  </div>
</template>
