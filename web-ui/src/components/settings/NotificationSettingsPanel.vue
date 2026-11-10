<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Send, TestTube2, Trash2, Webhook } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { NotificationSettings, NotificationSettingsUpdate, NotificationTestResponse } from '@/api/settings'

type FieldKey = keyof NotificationSettingsUpdate

const props = defineProps<{
  settings: NotificationSettings
  isReady: boolean
  isSaving: boolean
  saveSettings: (payload: NotificationSettingsUpdate) => Promise<void>
  testSettings: (payload: { channel?: string; settings: NotificationSettingsUpdate }) => Promise<NotificationTestResponse>
}>()
const { t } = useI18n()

const WEBHOOK_HEADERS_EXAMPLE = '{"Authorization":"Bearer token"}'
const WEBHOOK_QUERY_EXAMPLE = '{"task":"{{title}}"}'
// Discord Webhook 可直接使用這個範例
const WEBHOOK_BODY_EXAMPLE = '{"content":"{{title}}\\n{{content}}"}'
const WEBHOOK_TEMPLATE_VARIABLES = '{{title}}, {{content}}, {{price}}, {{reason}}, {{link}}, {{image_url}}'

// 會被後端遮蔽、不回傳內容的欄位：留空代表沿用已儲存的值
const secretFields: FieldKey[] = ['WEBHOOK_URL', 'WEBHOOK_HEADERS']
const textFields: FieldKey[] = ['WEBHOOK_METHOD', 'WEBHOOK_CONTENT_TYPE', 'WEBHOOK_QUERY_PARAMETERS', 'WEBHOOK_BODY']

const initialValues = reactive<Record<string, string>>({})
const form = reactive<Record<string, string>>({})
const clearedFields = reactive<Record<string, boolean>>({})
const testResult = ref<{ success: boolean; message: string; label: string } | null>(null)
const isTesting = ref(false)

function syncFromSettings(settings: NotificationSettings) {
  initialValues.WEBHOOK_METHOD = settings.WEBHOOK_METHOD ?? 'POST'
  initialValues.WEBHOOK_CONTENT_TYPE = settings.WEBHOOK_CONTENT_TYPE ?? 'JSON'
  initialValues.WEBHOOK_QUERY_PARAMETERS = settings.WEBHOOK_QUERY_PARAMETERS ?? ''
  initialValues.WEBHOOK_BODY = settings.WEBHOOK_BODY ?? ''
  Object.assign(form, initialValues, { WEBHOOK_URL: '', WEBHOOK_HEADERS: '' })
  for (const field of Object.keys(clearedFields)) {
    clearedFields[field] = false
  }
}

watch(() => props.settings, syncFromSettings, { immediate: true, deep: true })

const isConfigured = computed(() => (props.settings.CONFIGURED_CHANNELS ?? []).includes('webhook'))
const urlHint = computed(() => (
  props.settings.WEBHOOK_URL_SET ? t('notifyPanel.secretKeepPlaceholder') : t('notifyPanel.notConfigured')
))

function updateField(field: FieldKey, value: string) {
  form[field] = value
  clearedFields[field] = false
}

function clearWebhook() {
  for (const field of [...secretFields, ...textFields]) {
    form[field] = ''
    clearedFields[field] = true
  }
  form.WEBHOOK_METHOD = 'POST'
  form.WEBHOOK_CONTENT_TYPE = 'JSON'
}

function buildPayload(): NotificationSettingsUpdate {
  const payload: Record<string, string | null> = {}
  for (const field of textFields) {
    if (clearedFields[field]) {
      payload[field] = null
      continue
    }
    const current = String(form[field] ?? '').trim()
    if (current !== String(initialValues[field] ?? '').trim()) {
      payload[field] = current || null
    }
  }
  for (const field of secretFields) {
    if (clearedFields[field]) {
      payload[field] = null
      continue
    }
    const value = String(form[field] ?? '').trim()
    if (value) {
      payload[field] = value
    }
  }
  return payload as NotificationSettingsUpdate
}

async function handleSave() {
  await props.saveSettings(buildPayload())
}

async function handleTest() {
  isTesting.value = true
  try {
    const response = await props.testSettings({ channel: 'webhook', settings: buildPayload() })
    testResult.value = response.results.webhook ?? null
  } finally {
    isTesting.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="!isReady" class="app-surface py-10 text-center text-sm text-slate-500">
      {{ t('notifyPanel.loading') }}
    </div>

    <Card v-else class="app-surface-subtle overflow-hidden border-l-4 border-l-rose-500">
      <CardHeader>
        <div class="flex items-start justify-between gap-3">
          <div class="space-y-2">
            <CardTitle class="flex items-center gap-2">
              <Webhook class="h-4 w-4 text-rose-500" /> {{ t('notifyPanel.webhook.title') }}
            </CardTitle>
            <CardDescription>{{ t('notifyPanel.webhook.description') }}</CardDescription>
          </div>
          <Badge :variant="isConfigured ? 'default' : 'outline'">
            {{ isConfigured ? t('common.active') : t('common.inactive') }}
          </Badge>
        </div>
      </CardHeader>
      <CardContent class="grid gap-4">
        <div class="grid gap-2">
          <Label>{{ t('notifyPanel.webhook.urlLabel') }}</Label>
          <Input
            :model-value="form.WEBHOOK_URL ?? ''"
            placeholder="https://discord.com/api/webhooks/..."
            @update:model-value="(value) => updateField('WEBHOOK_URL', String(value))"
          />
          <p class="text-xs text-slate-500">{{ urlHint }}</p>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="grid gap-2">
            <Label>{{ t('notifyPanel.webhook.methodLabel') }}</Label>
            <Select :model-value="form.WEBHOOK_METHOD || 'POST'" @update:model-value="(value) => updateField('WEBHOOK_METHOD', String(value))">
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="POST">POST</SelectItem><SelectItem value="GET">GET</SelectItem></SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label>{{ t('notifyPanel.webhook.contentTypeLabel') }}</Label>
            <Select :model-value="form.WEBHOOK_CONTENT_TYPE || 'JSON'" @update:model-value="(value) => updateField('WEBHOOK_CONTENT_TYPE', String(value))">
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="JSON">JSON</SelectItem><SelectItem value="FORM">FORM</SelectItem></SelectContent>
            </Select>
          </div>
        </div>
        <div class="grid gap-2">
          <Label>{{ t('notifyPanel.webhook.bodyLabel') }}</Label>
          <Textarea
            :model-value="form.WEBHOOK_BODY ?? ''"
            :placeholder="`${t('notifyPanel.webhook.bodyPlaceholder')}${WEBHOOK_BODY_EXAMPLE}`"
            @update:model-value="(value) => updateField('WEBHOOK_BODY', String(value))"
          />
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="grid gap-2">
            <Label>{{ t('notifyPanel.webhook.headersLabel') }}</Label>
            <Textarea
              :model-value="form.WEBHOOK_HEADERS ?? ''"
              :placeholder="`${t('notifyPanel.webhook.headersPlaceholder')}${WEBHOOK_HEADERS_EXAMPLE}`"
              @update:model-value="(value) => updateField('WEBHOOK_HEADERS', String(value))"
            />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('notifyPanel.webhook.queryLabel') }}</Label>
            <Textarea
              :model-value="form.WEBHOOK_QUERY_PARAMETERS ?? ''"
              :placeholder="`${t('notifyPanel.webhook.queryPlaceholder')}${WEBHOOK_QUERY_EXAMPLE}`"
              @update:model-value="(value) => updateField('WEBHOOK_QUERY_PARAMETERS', String(value))"
            />
          </div>
        </div>
        <div class="rounded-2xl border border-dashed border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-700">
          <p>{{ t('notifyPanel.webhook.variablesHelp') }}</p>
          <p class="mt-2 break-all font-mono text-xs text-rose-900">{{ WEBHOOK_TEMPLATE_VARIABLES }}</p>
        </div>
        <div
          v-if="testResult"
          class="rounded-2xl border px-4 py-3 text-sm"
          :class="testResult.success ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'"
        >
          {{ testResult.label }}：{{ testResult.message }}
        </div>
      </CardContent>
      <CardFooter class="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" :disabled="props.isSaving" @click="clearWebhook">
          <Trash2 class="h-4 w-4" />{{ t('notifyPanel.clear') }}
        </Button>
        <Button variant="outline" :disabled="props.isSaving || isTesting" @click="handleTest">
          <TestTube2 class="h-4 w-4" />{{ isTesting ? t('common.testing') : t('notifyPanel.test') }}
        </Button>
        <Button :disabled="props.isSaving" @click="handleSave">
          <Send class="h-4 w-4" />{{ t('notifyPanel.save') }}
        </Button>
      </CardFooter>
    </Card>
  </div>
</template>
