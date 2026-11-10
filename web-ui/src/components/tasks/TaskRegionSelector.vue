<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// 臺灣 22 縣市；值會拿去比對蝦皮商品的「出貨地」文字
const TAIWAN_REGIONS = [
  '台北市', '新北市', '基隆市', '桃園市', '新竹市', '新竹縣', '苗栗縣',
  '台中市', '彰化縣', '南投縣', '雲林縣', '嘉義市', '嘉義縣',
  '台南市', '高雄市', '屏東縣', '宜蘭縣', '花蓮縣', '台東縣',
  '澎湖縣', '金門縣', '連江縣',
]

const props = defineProps<{
  modelValue?: string | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()
const { t } = useI18n()

const current = computed(() => String(props.modelValue || '').trim())
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-2">
      <div class="min-w-[12rem] flex-1">
        <Select
          :model-value="current"
          @update:model-value="(value) => emit('update:modelValue', String(value || ''))"
        >
          <SelectTrigger>
            <SelectValue :placeholder="t('tasks.region.provincePlaceholder')" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="option in TAIWAN_REGIONS" :key="option" :value="option">
              {{ option }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
      <Button type="button" variant="ghost" size="sm" @click="emit('update:modelValue', '')">
        {{ t('tasks.region.clear') }}
      </Button>
    </div>
    <p class="text-xs text-slate-500">{{ t('tasks.region.helper') }}</p>
  </div>
</template>
