<script setup>
// 证件照管理面板：作为 AdminView「证件照管理」tab 的内容组件（原 /cert-admin 独立页已移除，
// 见 doc/AGENTS.md 6.9）。全部模板统一设置项：启停 + 独立单价（留空=按标准页价）；
// 证照件按 单价×页数（1 页/版）、两页合一按 单价×版面数 计。系统设置：生成件保留
// 时长、每日生成上限。版式与卡片文案随代码发布，P0 只读展示。
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { BadgeCheck, RefreshCw, Settings2 } from 'lucide-vue-next'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  fetchAdminCertSettings,
  fetchAdminCertTemplates,
  updateAdminCertSettings,
  updateAdminCertTemplate,
} from './api'

const loading = ref(true)
const loadError = ref(false)
const templates = ref([])
const savingCode = ref('')
const settingsSaving = ref(false)
const settingsForm = ref({ cert_retention_hours: 24, cert_daily_generate_limit: 20 })

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const [list, settings] = await Promise.all([fetchAdminCertTemplates(), fetchAdminCertSettings()])
    templates.value = list.map((item) => ({
      ...item,
      draftPrice: item.price == null ? '' : String(item.price),
    }))
    settingsForm.value = { ...settings }
  } catch (error) {
    loadError.value = true
    toast.error(error?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function saveTemplate(item) {
  const priceText = String(item.draftPrice).trim()
  let price = null
  if (priceText !== '') {
    price = Number(priceText)
    if (!Number.isFinite(price) || price <= 0 || price > 100000) {
      toast.warning('单价需为正数（留空表示按标准页价）')
      return
    }
  }
  savingCode.value = item.code
  try {
    const updated = await updateAdminCertTemplate(item.code, { price, enabled: Boolean(item.enabled) })
    Object.assign(item, updated, { draftPrice: updated.price == null ? '' : String(updated.price) })
    toast.success(`「${item.name}」已保存`)
  } catch (error) {
    toast.error(error?.message || '保存失败')
  } finally {
    savingCode.value = ''
  }
}

async function saveSettings() {
  const retention = Number(settingsForm.value.cert_retention_hours)
  const limit = Number(settingsForm.value.cert_daily_generate_limit)
  if (!Number.isInteger(retention) || retention < 0 || retention > 8760) {
    toast.warning('保留时长需为 0–8760 之间的整数小时')
    return
  }
  if (!Number.isInteger(limit) || limit < 0 || limit > 100000) {
    toast.warning('每日生成上限需为 0–100000 之间的整数（0 为不限制）')
    return
  }
  settingsSaving.value = true
  try {
    settingsForm.value = await updateAdminCertSettings({ cert_retention_hours: retention, cert_daily_generate_limit: limit })
    toast.success('设置已保存，即时生效')
  } catch (error) {
    toast.error(error?.message || '保存失败')
  } finally {
    settingsSaving.value = false
  }
}
</script>

<template>
  <div class="grid gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="grid gap-1">
        <p class="text-[13px] font-bold tracking-widest text-primary">证照打印</p>
        <h2 class="font-display text-2xl font-bold tracking-tight">证件照管理</h2>
      </div>
      <Button variant="secondary" class="h-9" :disabled="loading" @click="load">
        <RefreshCw />
        刷新
      </Button>
    </div>
    <small class="text-xs leading-relaxed text-muted-foreground">
      全部模板统一支持启停与独立单价（证照件按 1 页/版、两页合一按版面数计），即时生效
      （停用后门户卡片消失、功能页显示已下架）；版式与卡片文案随版本发布。
    </small>

    <div v-if="loading" class="grid gap-2">
      <Skeleton v-for="n in 3" :key="n" class="h-24 rounded-xl" />
    </div>
    <Alert v-else-if="loadError" variant="destructive">
      <AlertTitle>模板列表加载失败</AlertTitle>
      <AlertDescription>
        <Button size="sm" variant="outline" class="mt-2 h-8" @click="load">重试</Button>
      </AlertDescription>
    </Alert>

    <template v-else>
      <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
        <div class="grid gap-1">
          <p class="text-[13px] font-bold tracking-widest text-primary">模板管理</p>
          <h3 class="font-display text-lg font-bold">全部门板</h3>
        </div>
        <div class="grid gap-2.5">
          <div v-for="item in templates" :key="item.code" class="grid gap-3 rounded-xl border bg-card p-3.5 lg:grid-cols-[minmax(0,1fr)_auto]">
            <div class="grid min-w-0 gap-1.5">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-sm font-bold text-foreground">{{ item.name }}</span>
                <Badge v-if="item.enabled" class="gap-1"><BadgeCheck class="size-3" aria-hidden="true" />已启用</Badge>
                <Badge v-else variant="outline" class="text-muted-foreground">已停用</Badge>
                <Badge variant="secondary" class="text-[11px]">{{ item.code }}</Badge>
              </div>
              <p class="text-xs text-muted-foreground">{{ item.card?.desc || '—' }}</p>
            </div>
            <div class="flex flex-wrap items-end gap-3 lg:justify-end">
              <label class="flex cursor-pointer items-center gap-2 text-sm">
                <Switch
                  :model-value="Boolean(item.enabled)"
                  @update:model-value="(value) => (item.enabled = value ? 1 : 0)"
                />
                <span class="text-muted-foreground">{{ item.enabled ? '启用' : '停用' }}</span>
              </label>
              <div class="flex w-44 flex-col gap-1.5">
                <Label :for="`cert-price-${item.code}`" class="text-xs text-muted-foreground">独立单价（元/页）</Label>
                <Input
                  :id="`cert-price-${item.code}`"
                  v-model="item.draftPrice"
                  inputmode="decimal"
                  placeholder="留空 = 按标准页价"
                  class="h-9 bg-background"
                />
              </div>
              <Button variant="secondary" class="h-9" :disabled="savingCode === item.code" @click="saveTemplate(item)">
                {{ savingCode === item.code ? '保存中…' : '保存' }}
              </Button>
            </div>
          </div>
          <div v-if="templates.length === 0" class="rounded-lg border border-dashed bg-card px-4 py-8 text-center text-sm text-muted-foreground">暂无模板</div>
        </div>
      </section>

      <section class="grid gap-3 rounded-xl border bg-muted/40 p-4">
        <div class="grid gap-1">
          <p class="text-[13px] font-bold tracking-widest text-primary">系统设置</p>
          <h3 class="font-display text-lg font-bold">保留期与生成上限</h3>
        </div>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="grid gap-1.5">
            <Label for="cert-retention" class="text-sm font-bold">生成件保留时长（小时）</Label>
            <Input
              id="cert-retention"
              v-model.number="settingsForm.cert_retention_hours"
              type="number"
              min="0"
              max="8760"
              class="h-10 bg-card"
            />
          </div>
          <div class="grid gap-1.5">
            <Label for="cert-daily-limit" class="text-sm font-bold">每用户每日生成上限</Label>
            <Input
              id="cert-daily-limit"
              v-model.number="settingsForm.cert_daily_generate_limit"
              type="number"
              min="0"
              max="100000"
              class="h-10 bg-card"
            />
          </div>
        </div>
        <small class="text-xs leading-relaxed text-muted-foreground">
          保留时长到期自动删除生成件与文件记录（跳过未完成订单）；每日生成上限 0 表示不限制，超限后当日无法继续生成。保存后即时生效。
        </small>
        <Button class="h-10 w-fit" :disabled="settingsSaving" @click="saveSettings">
          <Settings2 />
          {{ settingsSaving ? '保存中…' : '保存设置' }}
        </Button>
      </section>
    </template>
  </div>
</template>
