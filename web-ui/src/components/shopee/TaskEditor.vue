<script setup lang="ts">
import { computed, onMounted, ref, toRaw, watch } from 'vue'
import { X, Info, Sparkles } from 'lucide-vue-next'
import type { Provider, ShopeeTask } from '@/api/shopee'
import { sanitizeCapabilities, scheduleOptions, taiwanRegions, validateTask } from '@/lib/shopee'
const props = defineProps<{ task: ShopeeTask; providers: Provider[]; busy: boolean; error: string; aiConfigured: boolean; timezone: string }>()
const emit = defineEmits<{ close: []; save: [task: ShopeeTask] }>()
const dialog = ref<HTMLDialogElement>()
const draft = ref<ShopeeTask>(structuredClone(toRaw(props.task)))
const minimum = ref<string | number>(props.task.min_price === null ? '' : String(props.task.min_price))
const maximum = ref<string | number>(props.task.max_price === null ? '' : String(props.task.max_price))
const excluded = ref(props.task.exclude_keywords.join('、'))
const schedule = ref(scheduleOptions.some(option => option.value === (props.task.cron ?? '')) ? (props.task.cron ?? '') : 'custom')
const cron = ref(props.task.cron ?? '')
const errors = ref<string[]>([])
const provider = computed(() => props.providers.find(item => item.id === draft.value.provider))
const capabilities = computed(() => provider.value?.capabilities ?? {})
watch(() => draft.value.provider, () => { draft.value = sanitizeCapabilities(draft.value, provider.value) })
onMounted(() => dialog.value?.showModal())
function close() { if (!props.busy) emit('close') }
function save() {
  const task = sanitizeCapabilities({ ...draft.value, task_name: draft.value.task_name.trim(), keyword: draft.value.keyword.trim(), min_price: String(minimum.value).trim() === '' ? null : Number(minimum.value), max_price: String(maximum.value).trim() === '' ? null : Number(maximum.value), exclude_keywords: excluded.value.split(/[,，、\n]/).map(value => value.trim()).filter(Boolean), cron: schedule.value === 'custom' ? cron.value.trim() : schedule.value || null }, provider.value)
  errors.value = validateTask(task, provider.value)
  if (schedule.value === 'custom' && !cron.value.trim()) errors.value.push('請輸入自訂 Cron。')
  if (task.decision_mode === 'ai' && !props.aiConfigured) errors.value.push('請先到「AI 與通知設定」設定 AI 服務，或改用關鍵字判斷。')
  if (!errors.value.length) emit('save', task)
}
</script>
<template>
  <dialog ref="dialog" class="task-dialog" aria-labelledby="task-editor-title" @cancel.prevent="close">
    <form @submit.prevent="save">
      <header class="dialog-header"><div><span class="eyebrow">監控條件</span><h2 id="task-editor-title">{{ task.id === undefined ? '建立新監控任務' : '編輯監控任務' }}</h2></div><button type="button" class="icon-button" aria-label="關閉任務編輯" :disabled="busy" @click="close"><X :size="21" /></button></header>
      <div class="dialog-content">
        <div class="info-line"><Info :size="17" /><span>目前只會處理模擬或已合法匯入的資料，不會搜尋蝦皮全站。</span></div>
        <section class="form-section"><h3><span>01</span> 基本設定</h3>
          <div class="form-grid">
            <label class="field">任務名稱 <span class="required">*</span><input v-model="draft.task_name" required maxlength="100" placeholder="例如 RTX 5070 Ti 二手監控" /></label>
            <label class="field">資料來源<select v-model="draft.provider"><option v-for="source in providers" :key="source.id" :value="source.id" :disabled="!source.available">{{ source.name }}{{ !source.available ? '（尚未授權）' : '' }}</option></select></label>
            <label class="field">搜尋關鍵字 <span class="required">*</span><input v-model="draft.keyword" required maxlength="200" placeholder="例如 Mac mini M4" /></label>
            <label class="field">判斷模式<select v-model="draft.decision_mode"><option value="keyword">關鍵字判斷</option><option value="ai">EagleEye AI 分析</option></select></label>
            <label class="field full">詳細購買需求<textarea v-model="draft.description" rows="3" maxlength="6000" placeholder="描述規格、保固、外觀、可接受的風險及其他購買條件。" /></label>
          </div>
          <label class="check"><input v-model="draft.analyze_images" type="checkbox" :disabled="draft.decision_mode !== 'ai'" /><span>啟用商品圖片分析 <small>僅適用於 AI 模式及允許使用的圖片</small></span></label>
          <p v-if="draft.decision_mode === 'ai'" class="small muted">AI 結果以實際資料為限，缺少的證據標示為「資訊不足」，不視為購買保證。</p>
        </section>
        <section class="form-section"><h3><span>02</span> 搜尋與篩選</h3>
          <div class="form-grid">
            <label class="field">最低價格（NT$）<input v-model="minimum" type="number" min="0" step="0.01" placeholder="不限" /></label>
            <label class="field">最高價格（NT$）<input v-model="maximum" type="number" min="0" step="0.01" placeholder="不限" /></label>
            <label class="field">最多搜尋筆數<input v-model.number="draft.max_items" type="number" min="1" max="500" required /></label>
            <label class="field">最多搜尋頁數<input v-model.number="draft.max_pages" type="number" min="1" max="20" required /></label>
            <label class="field">商品類別 <small v-if="!capabilities.category">此來源不支援</small><input v-model="draft.category" :disabled="!capabilities.category" placeholder="不限類別" /></label>
            <label class="field">商品狀態 <small v-if="!capabilities.condition">此來源不支援</small><select v-model="draft.condition" :disabled="!capabilities.condition"><option :value="null">全部</option><option value="new">新品</option><option value="used">二手</option></select></label>
            <label class="field">賣家所在地 <small v-if="!capabilities.region">此來源不支援</small><select v-model="draft.region" :disabled="!capabilities.region"><option :value="null">臺灣所有縣市</option><option v-for="region in taiwanRegions" :key="region" :value="region">{{ region }}</option></select></label>
            <label class="field">賣家條件 <small v-if="!capabilities.seller_type">此來源無可靠資料</small><select v-model="draft.seller_type" :disabled="!capabilities.seller_type"><option :value="null">全部</option><option value="personal">僅個人賣家</option><option value="business">僅商家</option></select></label>
            <label class="field full">排除關鍵字<input v-model="excluded" placeholder="配件、空盒、支架（以頓號或逗號分隔）" /></label>
          </div>
          <label class="check"><input v-model="draft.exclude_ads" type="checkbox" :disabled="!capabilities.ads" /><span>排除廣告商品 <small>{{ capabilities.ads ? '只依資料來源提供的廣告標記篩選' : '此來源無法識別廣告，已停用' }}</small></span></label>
          <p class="small muted">未提供狀態、地區或賣家類型的商品不會被推測分類。啟用這些篩選時可能排除資訊不足的商品。</p>
        </section>
        <section class="form-section"><h3><span>03</span> 排程與通知</h3>
          <div class="form-grid">
            <label class="field">執行頻率<select v-model="schedule"><option v-for="option in scheduleOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label class="field">Discord 通知範圍<select v-model="draft.notify"><option value="recommended">僅推薦商品</option><option value="all">所有符合條件商品</option></select></label>
            <label v-if="schedule === 'custom'" class="field full">自訂 Cron<input v-model="cron" placeholder="例如 0 */2 * * *" /><small>分 時 日 月 星期，排程時區：{{ timezone || 'Asia/Taipei' }}。儲存時由伺服器驗證。</small></label>
          </div>
          <div class="check-row"><label class="check"><input v-model="draft.enabled" type="checkbox" /><span>啟用任務與自動排程</span></label><label class="check"><input v-model="draft.notify_price_drop" type="checkbox" /><span>價格下降時再次通知</span></label></div>
          <p class="small muted">模擬資料只供測試；排程不代表已開通即時搜尋。未設定 Discord Webhook 時不會傳送通知。</p>
        </section>
        <details class="prompt-details"><summary><Sparkles :size="17" /> 此任務的自訂 AI 提示詞</summary><label class="field">補充分析指示<textarea v-model="draft.custom_prompt" rows="5" placeholder="選填。將附加至預設分析提示詞；請保留缺乏證據時標示資訊不足的原則。" /></label></details>
        <div v-if="errors.length || error" class="inline-error" role="alert"><ul><li v-for="item in errors" :key="item">{{ item }}</li></ul><p v-if="error">{{ error }}</p></div>
      </div>
      <footer class="dialog-footer"><span class="small muted">* 為必填欄位</span><div class="button-row"><button type="button" class="button" :disabled="busy" @click="close">取消</button><button class="button primary" :disabled="busy">{{ busy ? '正在儲存…' : '儲存任務' }}</button></div></footer>
    </form>
  </dialog>
</template>
