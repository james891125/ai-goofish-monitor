<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { Activity, ArrowDown, ArrowUpRight, Bell, Check, ChevronRight, Clock3, Database, FileJson, History, Info, LayoutDashboard, LogOut, PackageSearch, Pencil, Play, Plus, RefreshCw, Search, Settings2, ShieldCheck, ShoppingBag, Sparkles, Trash2, TriangleAlert, X } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import { shopeeApi, type PricePoint, type Product, type Run, type Settings, type ShopeeTask, type SourceStatus } from '@/api/shopee'
import { formatDate, formatPrice, newTask, parseImport, safeImageUrl, safeProductUrl, sampleTask, scheduleLabel } from '@/lib/shopee'
import TaskEditor from '@/components/shopee/TaskEditor.vue'
import BrowserSnapshotPanel from '@/components/shopee/BrowserSnapshotPanel.vue'

const route = useRoute()
const { username, logout } = useAuth()
const section = computed(() => String(route.name ?? 'tasks'))
const navigation = [
  { id: 'tasks', name: '監控任務', icon: LayoutDashboard },
  { id: 'results', name: '商品與推薦', icon: PackageSearch },
  { id: 'sources', name: '資料來源', icon: Database },
  { id: 'history', name: '執行紀錄', icon: History },
  { id: 'settings', name: 'AI 與通知設定', icon: Settings2 },
]
const descriptions: Record<string, string> = { tasks: '設定搜尋條件，讓每一次發現都有依據。', results: '檢視收集到的商品、分析理由與價格變化。', sources: '只使用有權取得的資料，清楚呈現每個來源的能力。', history: '追蹤每次執行、通知與錯誤，確認監控是否如預期。', settings: '連接您的 AI 服務，調整分析方式與 Discord 通知。' }
const status = ref<SourceStatus | null>(null)
const tasks = ref<ShopeeTask[]>([])
const products = ref<Product[]>([])
const runs = ref<Run[]>([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const success = ref('')
const search = ref('')
const selectedTask = ref('')
const recommendedOnly = ref(false)
const editor = ref<ShopeeTask | null>(null)
const editorBusy = ref(false)
const editorError = ref('')
const busyTask = ref<number | null>(null)
const importContent = ref('')
const rightsConfirmed = ref(false)
const importBusy = ref(false)
const settings = ref<Settings>({ OPENAI_BASE_URL: '', OPENAI_MODEL_NAME: '' })
const apiKey = ref('')
const webhook = ref('')
const settingsLoaded = ref(false)
const settingsBusy = ref(false)
const prompt = ref('')
const promptLoaded = ref(false)
const promptBusy = ref(false)
const selectedProduct = ref<Product | null>(null)
const priceHistory = ref<PricePoint[]>([])
const historyBusy = ref(false)
const historyError = ref('')
const historyDialog = ref<HTMLDialogElement>()
let timer: ReturnType<typeof setInterval> | undefined
let messageTimer: ReturnType<typeof setTimeout> | undefined
let historyRequest = 0
const title = computed(() => navigation.find(item => item.id === section.value)?.name ?? '監控任務')
const visibleTasks = computed(() => tasks.value.filter(task => `${task.task_name} ${task.keyword}`.toLowerCase().includes(search.value.toLowerCase())))
const activeCount = computed(() => tasks.value.filter(task => task.enabled).length)
const filteredProducts = computed(() => products.value.filter(product => (!selectedTask.value || product.task_id === Number(selectedTask.value)) && (!recommendedOnly.value || isRecommended(product)) && `${product.title} ${product.description ?? ''}`.toLowerCase().includes(search.value.toLowerCase())))
const filteredRuns = computed(() => runs.value.filter(run => !selectedTask.value || run.task_id === Number(selectedTask.value)))
const latestRun = computed(() => runs.value[0])
const canCreate = computed(() => !!status.value?.providers.some(provider => provider.available))
const importPlaceholder = `[
  {
    "platform": "shopee_tw",
    "product_id": "請填入實際商品 ID",
    "title": "請填入有權使用的商品名稱",
    "price_twd": 15000,
    "description": "商品原始描述",
    "images": [],
    "images_allowed": false,
    "product_url": "https://shopee.tw/product/店家ID/商品ID",
    "condition": null,
    "seller": { "seller_id": null, "name": null, "rating": null, "review_count": null, "location": null, "verified_type": null }
  }
]`

function message(text: string) {
  success.value = text
  if (messageTimer) clearTimeout(messageTimer)
  messageTimer = setTimeout(() => { success.value = '' }, 7000)
}
function errorMessage(value: unknown): string { return value instanceof Error ? value.message : '操作未完成，請稍後再試。' }
function taskName(id: number): string { return tasks.value.find(task => task.id === id)?.task_name ?? `任務 #${id}（已刪除或無法取得）` }
function sourceName(id: string): string { return status.value?.providers.find(source => source.id === id)?.name ?? (id === 'mock' ? '模擬資料' : id === 'import' ? '合法匯入' : id === 'browser_experiment' ? '實驗瀏覽快照（手動更新）' : id) }
function isSnapshotTask(id: number): boolean { return tasks.value.some(task => task.id === id && task.provider === 'browser_experiment') }
function sourceDescription(id: string): string {
  if (id === 'mock') return '固定測試資料，用於驗證篩選、分析、排程與去重。不是即時商品或市場行情。'
  if (id === 'import') return '使用您有權使用的商品 JSON。只處理提供的資料，不會自動開啟或擷取商品網址。'
  if (id === 'browser_experiment') return '手動匯入本機瀏覽工具產生的文字快照，最多 5 筆。任務只重新分析最近匯入的快照並保留 AI 判斷，不會啟動瀏覽器、排程或發現新商品。可使用不代表已獲平台授權。'
  return '尚未連接經驗證的全站搜尋服務。官方或第三方授權需確認適用範圍、欄位及使用限制。'
}
function isRecommended(product: Product): boolean { return product.analysis?.recommended === true || product.analysis?.is_recommended === true }
function analysisReason(product: Product): string {
  const reason = product.analysis?.reason ?? product.analysis?.reasoning ?? product.analysis?.summary
  return typeof reason === 'string' ? reason : '資訊不足：尚無可顯示的分析理由。'
}
function riskTags(product: Product): string[] {
  const risks = product.analysis?.risks ?? product.analysis?.risk_tags
  return Array.isArray(risks) ? risks.filter((item): item is string => typeof item === 'string') : []
}
function runStatus(run: Run): string { return ({ completed: '執行完成', success: '執行完成', failed: '執行失敗', error: '執行失敗', running: '執行中', started: '執行中', skipped: '略過' } as Record<string, string>)[run.status] ?? run.status }
function authorizationLabel(value: string): string { return ({ not_required: '不需帳號授權', authorized: '已授權', active: '已授權', waiting_authorization: '等待資料來源授權', unavailable: '尚未授權', missing: '尚未授權', expired: '授權已到期', mock: '模擬測試', user_provided: '由使用者確認權限', experimental_unverified: '實驗功能：平台授權尚未驗證' } as Record<string, string>)[value] ?? '請確認來源授權' }
async function refresh(silent = false) {
  if (refreshing.value) return
  refreshing.value = true
  if (!silent) error.value = ''
  try {
    const [nextStatus, nextTasks, nextProducts, nextRuns] = await Promise.all([shopeeApi.status(), shopeeApi.tasks(), shopeeApi.products(), shopeeApi.runs()])
    status.value = nextStatus; tasks.value = nextTasks; products.value = nextProducts; runs.value = nextRuns
  } catch (cause) { error.value = `無法更新監控資料：${errorMessage(cause)}` }
  finally { loading.value = false; refreshing.value = false }
}
function openEditor(task?: ShopeeTask) { editorError.value = ''; editor.value = task ? structuredClone(toRaw(task)) : newTask() }
async function saveTask(task: ShopeeTask) {
  if (editorBusy.value) return
  editorBusy.value = true; editorError.value = ''
  try { await shopeeApi.saveTask(task); editor.value = null; message('監控任務已儲存。'); await refresh(true) }
  catch (cause) { editorError.value = errorMessage(cause) }
  finally { editorBusy.value = false }
}
async function runTask(task: ShopeeTask) {
  if (task.id === undefined || busyTask.value !== null || task.is_running) return
  busyTask.value = task.id; error.value = ''
  try { await shopeeApi.runTask(task.id); message(task.provider === 'browser_experiment' ? '已要求重新分析最近匯入的實驗快照，不會瀏覽網站或收集新商品。結果會自動更新。' : '已送出執行要求，結果會自動更新。'); await refresh(true) }
  catch (cause) { error.value = errorMessage(cause) }
  finally { busyTask.value = null }
}
async function toggleTask(task: ShopeeTask) {
  if (task.id === undefined || busyTask.value !== null) return
  busyTask.value = task.id
  try { await shopeeApi.saveTask({ ...task, enabled: !task.enabled }); message(task.enabled ? '已停用任務。' : task.provider === 'browser_experiment' ? '已啟用手動快照分析，不會啟動排程。' : '已啟用任務。'); await refresh(true) }
  catch (cause) { error.value = errorMessage(cause) }
  finally { busyTask.value = null }
}
async function deleteTask(task: ShopeeTask) {
  if (task.id === undefined || busyTask.value !== null) return
  if (!window.confirm(`確定刪除「${task.task_name}」？既有商品與歷史紀錄會保留。`)) return
  busyTask.value = task.id
  try { await shopeeApi.deleteTask(task.id); message('已刪除監控任務，歷史資料仍保留。'); await refresh(true) }
  catch (cause) { error.value = errorMessage(cause) }
  finally { busyTask.value = null }
}
async function readImportFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (file.size > 5 * 1024 * 1024) { error.value = 'JSON 檔案不可超過 5 MB。'; input.value = ''; return }
  try { importContent.value = await file.text(); rightsConfirmed.value = false; error.value = '' }
  catch { error.value = '無法讀取檔案，請確認檔案格式與權限。' }
  input.value = ''
}
async function importProducts() {
  if (importBusy.value) return
  error.value = ''
  if (!rightsConfirmed.value) { error.value = '請先確認您有權使用及匯入這些資料。'; return }
  let parsed: unknown[]
  try { parsed = parseImport(importContent.value) } catch (cause) { error.value = cause instanceof SyntaxError ? 'JSON 格式不正確，請檢查引號、逗號及括號。' : errorMessage(cause); return }
  importBusy.value = true
  try { const result = await shopeeApi.importProducts(parsed); message(`已匯入 ${result.imported} 筆商品。請建立或執行「合法匯入」來源的任務以篩選及分析。`); importContent.value = ''; rightsConfirmed.value = false; await refresh(true) }
  catch (cause) { error.value = `匯入未完成：${errorMessage(cause)}` }
  finally { importBusy.value = false }
}
async function browserImported(count: number) {
  message(`已匯入 ${count} 筆實驗快照。請使用「實驗瀏覽快照（手動更新）」來源執行 AI 分析。要發現新商品，需重新執行收集工具並匯入。`)
  await refresh(true)
}
async function loadSettings() {
  if (settingsLoaded.value) return
  try { settings.value = await shopeeApi.settings(); settingsLoaded.value = true }
  catch (cause) { error.value = `無法讀取設定：${errorMessage(cause)}` }
  try { prompt.value = (await shopeeApi.prompt()).content; promptLoaded.value = true }
  catch (cause) { error.value = `無法讀取預設提示詞：${errorMessage(cause)}` }
}
async function saveSettings() {
  if (settingsBusy.value) return
  settingsBusy.value = true; error.value = ''
  const payload: Settings = { OPENAI_BASE_URL: settings.value.OPENAI_BASE_URL.trim(), OPENAI_MODEL_NAME: settings.value.OPENAI_MODEL_NAME.trim() }
  if (apiKey.value.trim()) payload.OPENAI_API_KEY = apiKey.value.trim()
  if (webhook.value.trim()) payload.DISCORD_WEBHOOK_URL = webhook.value.trim()
  try { await shopeeApi.saveSettings(payload); apiKey.value = ''; webhook.value = ''; settings.value = await shopeeApi.settings(); message('AI 與通知設定已儲存。'); await refresh(true) }
  catch (cause) { error.value = errorMessage(cause) }
  finally { settingsBusy.value = false }
}
async function savePrompt() {
  if (promptBusy.value || !prompt.value.trim()) return
  promptBusy.value = true; error.value = ''
  try { await shopeeApi.savePrompt(prompt.value); message('預設 AI 提示詞已儲存，後續執行將使用新內容。') }
  catch (cause) { error.value = errorMessage(cause) }
  finally { promptBusy.value = false }
}
async function showHistory(product: Product) {
  const request = ++historyRequest
  selectedProduct.value = product; priceHistory.value = []; historyBusy.value = true; historyError.value = ''
  historyDialog.value?.showModal()
  try { const points = await shopeeApi.history(product.product_id, product.task_id, product.data_source); if (request === historyRequest) priceHistory.value = points }
  catch (cause) { if (request === historyRequest) historyError.value = errorMessage(cause) }
  finally { if (request === historyRequest) historyBusy.value = false }
}
function closeHistory() { historyRequest++; historyDialog.value?.close(); selectedProduct.value = null }
watch(section, value => { search.value = ''; error.value = ''; editor.value = null; editorError.value = ''; closeHistory(); if (value === 'settings') void loadSettings() })
onMounted(async () => { await refresh(); if (section.value === 'settings') void loadSettings(); timer = setInterval(() => { if (!document.hidden) void refresh(true) }, 8000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer); if (messageTimer) clearTimeout(messageTimer); historyRequest++ })
</script>

<template>
  <div class="monitor-app">
    <aside class="sidebar">
      <RouterLink to="/tasks" class="brand"><span class="brand-icon"><ShoppingBag :size="25" /></span><span>蝦皮臺灣<span class="brand-sub">AI 商品監控</span></span></RouterLink>
      <div class="workspace-label">工作空間 <span>臺灣 · TWD</span></div>
      <nav aria-label="主要導覽"><RouterLink v-for="item in navigation" :key="item.id" :to="`/${item.id}`" :class="['nav-item', { active: section === item.id }]" :aria-label="item.name" :aria-current="section === item.id ? 'page' : undefined"><component :is="item.icon" :size="19" /><span>{{ item.name }}</span><ChevronRight v-if="section === item.id" :size="15" /></RouterLink></nav>
      <div class="sidebar-bottom"><div class="source-note"><ShieldCheck :size="19" /><strong>來源清楚，判斷有據</strong><p>匯入前須確認使用權，<br>不匯出帳號 Cookie。</p></div><div class="account"><span class="avatar">{{ (username || 'A').slice(0, 1).toUpperCase() }}</span><div><strong>{{ username || '管理員' }}</strong><small>系統管理員</small></div><button class="icon-button" title="登出" aria-label="登出" @click="logout"><LogOut :size="18" /></button></div></div>
    </aside>
    <div class="main-area">
      <header class="topbar"><div><span class="breadcrumb">監控中心</span><ChevronRight :size="14" /><strong>{{ title }}</strong></div><div><span class="topbar-status"><span class="status-dot" /> 可測試版本</span><button class="icon-button compact-logout" aria-label="登出" @click="logout"><LogOut :size="17" /></button></div></header>
      <main class="page-content">
        <section class="page-heading"><div><span class="eyebrow">SHOPEE TAIWAN MONITOR</span><h1>{{ title }}</h1><p>{{ descriptions[section] }}</p></div><div class="button-row"><button class="button" :disabled="refreshing" @click="refresh()"><RefreshCw :size="16" :class="{ spinning: refreshing }" /><span>重新整理</span></button><button v-if="section === 'tasks'" class="button primary" :disabled="!canCreate" @click="openEditor()"><Plus :size="18" />建立監控任務</button></div></section>
        <div class="notice" role="status"><TriangleAlert :size="20" /><div><strong>等待資料來源授權</strong><p>可測試模擬、合法匯入及手動更新的實驗快照。實驗功能可使用不代表已獲平台授權；尚未驗證臺灣蝦皮全站搜尋的正式來源，不能作為即時行情或全自動上線服務。</p></div><RouterLink v-if="section !== 'sources'" to="/sources">查看資料來源<ArrowUpRight :size="16" /></RouterLink></div>
        <div v-if="error" class="error-banner" role="alert"><TriangleAlert :size="18" /><span>{{ error }}</span><button class="icon-button" aria-label="關閉錯誤訊息" @click="error = ''"><X :size="17" /></button></div>
        <div v-if="success" class="success-banner" role="status"><Check :size="18" />{{ success }}</div>
        <div v-if="loading" class="empty-state"><RefreshCw class="spinning" :size="26" /><h3>正在載入監控資料</h3><p>連線完成後顯示實際資料，不會自動建立示範結果。</p></div>

        <template v-else-if="section === 'tasks'">
          <div class="stat-grid"><article class="stat-card"><span>監控任務<LayoutDashboard :size="18" /></span><strong>{{ tasks.length }}<small>個任務</small></strong><p>{{ activeCount }} 個已啟用 · {{ tasks.length - activeCount }} 個已停用</p></article><article class="stat-card"><span>已收集商品<PackageSearch :size="18" /></span><strong>{{ products.length }}<small>筆資料</small></strong><p>包含模擬與已匯入的快照結果</p></article><article class="stat-card"><span>符合條件商品<Sparkles :size="18" /></span><strong>{{ products.filter(isRecommended).length }}<small>筆結果</small></strong><p>{{ status?.ai_configured ? 'AI 服務已設定' : 'AI 尚未設定，請先完成服務設定' }}</p></article><article class="stat-card"><span>最近執行<Clock3 :size="18" /></span><strong class="stat-date">{{ latestRun ? formatDate(latestRun.started_at) : '尚未執行' }}</strong><p>{{ latestRun ? runStatus(latestRun) : '建立任務後即可開始測試' }}</p></article></div>
          <section class="panel task-panel"><div class="panel-header"><div><h2>我的監控任務 <span class="count">{{ tasks.length }}</span></h2><p>管理搜尋條件、排程與執行狀態</p></div><label class="search-field"><Search :size="17" /><input v-model="search" aria-label="搜尋任務" placeholder="搜尋任務或關鍵字" /></label></div>
            <div v-if="!visibleTasks.length" class="empty-state"><span class="empty-icon"><Search :size="28" /></span><h3>{{ search ? '找不到符合的任務' : '從第一個監控任務開始' }}</h3><p>{{ search ? '試試其他任務名稱或關鍵字。' : '選擇資料來源與搜尋條件，執行測試並累積價格紀錄。' }}</p><button v-if="!search" class="button primary" :disabled="!canCreate" @click="openEditor()"><Plus :size="17" />建立監控任務</button></div>
            <div v-else class="table-scroll"><table class="task-table"><thead><tr><th>任務與關鍵字</th><th>資料來源／模式</th><th>價格範圍</th><th>排程</th><th>狀態</th><th class="align-right">操作</th></tr></thead><tbody><tr v-for="task in visibleTasks" :key="task.id"><td><strong>{{ task.task_name }}</strong><span class="cell-sub">{{ task.keyword }}</span></td><td><span class="tag" :class="task.provider === 'mock' ? 'tag-amber' : 'tag-blue'">{{ sourceName(task.provider) }}</span><span class="cell-sub">{{ task.decision_mode === 'ai' ? 'AI 分析' : '關鍵字判斷' }}</span><span v-if="task.provider === 'browser_experiment'" class="cell-sub">僅最近匯入快照，不收集新商品</span></td><td><span class="price-range">{{ task.min_price === null && task.max_price === null ? '不限價格' : `${task.min_price === null ? '不限' : formatPrice(task.min_price)} – ${task.max_price === null ? '不限' : formatPrice(task.max_price)}` }}</span></td><td><span>{{ scheduleLabel(task.cron) }}</span><span class="cell-sub">{{ task.provider === 'browser_experiment' ? '不支援排程／自動瀏覽' : task.enabled && task.next_run_at ? `下次 ${formatDate(task.next_run_at)}` : task.enabled ? '尚無下次排程' : '排程已停用' }}</span></td><td><button class="task-state" :class="{ enabled: task.enabled }" :disabled="busyTask !== null || task.is_running" :aria-label="`${task.enabled ? '停用' : '啟用'}${task.task_name}`" @click="toggleTask(task)"><span class="status-dot" />{{ task.is_running ? '執行中' : task.enabled ? '已啟用' : '已停用' }}</button></td><td><div class="row-actions"><button class="button small-button" :disabled="busyTask !== null || task.is_running || !task.enabled" @click="runTask(task)"><Play :size="14" />{{ task.is_running ? '執行中' : task.provider === 'browser_experiment' ? '重新分析快照' : '執行' }}</button><button class="icon-button" :disabled="busyTask !== null || task.is_running" :aria-label="`編輯${task.task_name}`" @click="openEditor(task)"><Pencil :size="16" /></button><button class="icon-button danger" :disabled="busyTask !== null || task.is_running" :aria-label="`刪除${task.task_name}`" @click="deleteTask(task)"><Trash2 :size="16" /></button></div></td></tr></tbody></table></div>
          </section>
          <div class="section-heading"><h2>快速開始</h2><span>示範設定可編輯，價格不是市場行情</span></div><div class="template-grid"><button class="template-card" :disabled="!canCreate" @click="openEditor(sampleTask('rtx'))"><span class="template-symbol">RTX</span><div><span class="eyebrow">顯示卡監控範本</span><h3>RTX 5070 Ti</h3><p>NT$15,000–25,000 · 每 30 分鐘</p><small>檢視型號、記憶體、保固與維修風險</small></div><Plus :size="20" /></button><button class="template-card" :disabled="!canCreate" @click="openEditor(sampleTask('mac'))"><span class="template-symbol silver">M4</span><div><span class="eyebrow">桌上型電腦監控範本</span><h3>Mac mini M4</h3><p>自行設定價格 · 每小時</p><small>檢視 RAM、SSD、保固與商品狀態</small></div><Plus :size="20" /></button></div>
        </template>

        <template v-else-if="section === 'results'">
          <section class="panel"><div class="panel-header wrap"><div><h2>收集結果 <span class="count">{{ filteredProducts.length }}</span></h2><p>金額為新臺幣，未知欄位保留為「資訊不足」</p></div><div class="filter-row"><select v-model="selectedTask" aria-label="依任務篩選商品"><option value="">所有任務</option><option v-for="task in tasks" :key="task.id" :value="String(task.id)">{{ task.task_name }}</option></select><label class="check"><input v-model="recommendedOnly" type="checkbox" />僅推薦商品</label><label class="search-field"><Search :size="16" /><input v-model="search" aria-label="搜尋商品" placeholder="搜尋商品" /></label></div></div>
            <div v-if="!filteredProducts.length" class="empty-state"><PackageSearch :size="34" /><h3>尚無符合條件的商品</h3><p>先執行監控任務，或調整篩選條件。模擬結果會清楚標示來源。</p><RouterLink to="/tasks" class="button">前往監控任務<ArrowUpRight :size="15" /></RouterLink></div>
            <div v-else class="product-grid"><article v-for="product in filteredProducts" :key="`${product.task_id}-${product.product_id}`" class="product-card"><div class="product-image"><img v-if="product.images_allowed && safeImageUrl(product.images?.[0])" :src="safeImageUrl(product.images?.[0])" :alt="product.title" loading="lazy" referrerpolicy="no-referrer" /><PackageSearch v-else :size="36" /><span class="tag" :class="product.data_source === 'mock' ? 'tag-amber' : 'tag-blue'">{{ sourceName(product.data_source) }}</span></div><div class="product-body"><div class="product-flags"><span v-if="product.is_new" class="tag tag-blue">新發現</span><span v-if="product.price_changed" class="tag tag-amber"><Activity :size="12" />價格變動</span><span class="tag" :class="isRecommended(product) ? 'tag-green' : ''">{{ product.analysis?.mode === 'keyword' ? '符合關鍵字（非 AI 推薦）' : isRecommended(product) ? '推薦考慮' : product.analysis ? '未推薦／資訊不足' : '尚未分析' }}</span></div><h3>{{ product.title }}</h3><div class="product-price">{{ formatPrice(product.price_twd) }}<del v-if="product.original_price_twd">{{ formatPrice(product.original_price_twd) }}</del></div><p class="seller-line">{{ product.seller?.name || '賣家資訊不足' }} · {{ product.seller?.location || '地區資訊不足' }}</p><p v-if="product.data_source === 'browser_experiment'" class="small snapshot-product-note">手動匯入的文字快照，價格與庫存非即時資料。</p><p class="analysis-text">{{ analysisReason(product) }}</p><div v-if="riskTags(product).length" class="risk-tags"><span v-for="risk in riskTags(product)" :key="risk">{{ risk }}</span></div><div class="product-meta"><span>資料{{ product.data_quality === 'complete' ? '完整' : '部分缺漏' }}</span><span>{{ formatDate(product.collected_at) }}</span></div><div class="product-actions"><button class="button small-button" @click="showHistory(product)"><History :size="15" />價格紀錄</button><a v-if="safeProductUrl(product.product_url)" class="text-link" :href="safeProductUrl(product.product_url)" target="_blank" rel="noopener noreferrer">原始商品<ArrowUpRight :size="15" /></a><span v-else class="small muted">未提供有效商品連結</span></div></div></article></div>
          </section>
        </template>

        <template v-else-if="section === 'sources'">
          <div class="source-grid"><article v-for="source in status?.providers ?? []" :key="source.id" class="panel source-card"><div class="source-card-heading"><span class="source-icon"><component :is="source.id === 'mock' ? Sparkles : source.id === 'import' ? FileJson : ShieldCheck" :size="24" /></span><span class="tag" :class="source.id === 'browser_experiment' || !source.available ? 'tag-amber' : 'tag-green'">{{ source.id === 'browser_experiment' ? '實驗快照 · 未驗證授權' : source.available ? '可使用' : '等待授權' }}</span></div><h2>{{ source.name }}</h2><p>{{ sourceDescription(source.id) }}</p><div class="source-auth"><ShieldCheck :size="15" />{{ authorizationLabel(source.authorization_status) }}<small v-if="source.expires_at">到期：{{ formatDate(source.expires_at) }}</small></div><div class="capability-tags"><span v-for="(label, key) in { keyword: '關鍵字', price: '價格', category: '類別', condition: '新舊程度', region: '地區', seller_type: '賣家類型', ads: '廣告識別' }" :key="key" :class="{ supported: source.capabilities[key] }">{{ source.capabilities[key] ? '✓' : '—' }} {{ label }}</span></div></article></div>
          <BrowserSnapshotPanel :available="status?.providers.some(source => source.id === 'browser_experiment' && source.available) ?? false" @imported="browserImported" />
          <section class="panel import-panel"><div class="panel-header"><div><h2>合法商品資料匯入</h2><p>支援商品 JSON 陣列或 { products: [...] }，每次最多 500 筆、檔案上限 5 MB。</p></div><FileJson :size="24" /></div><form class="panel-body" @submit.prevent="importProducts"><div class="import-instructions"><strong>開始前請確認</strong><ul><li>資料來自您擁有或已取得授權的來源，並符合來源服務的使用條款。</li><li>價格以新臺幣填入 price_twd。無法取得的欄位使用 null，不推測賣家身分或信用。</li><li>不接受 Cookie、存取權杖或帳號密碼。商品網址不會觸發網站擷取。</li><li>圖片限 HTTPS 蝦皮 CDN。只有已取得圖片使用權時，才將 images_allowed 設為 true；否則不顯示圖片，也不送給 AI 或 Discord。</li></ul></div><label class="file-input">選擇 JSON 檔案<input type="file" accept="application/json,.json" :disabled="importBusy" @change="readImportFile" /></label><label class="field">商品 JSON<textarea v-model="importContent" class="code-input" rows="12" spellcheck="false" :placeholder="importPlaceholder" :disabled="importBusy" required /></label><label class="check rights-check"><input v-model="rightsConfirmed" type="checkbox" required :disabled="importBusy" /><span>我確認有權使用及匯入以上商品資料與圖片，並遵守資料來源的授權條件。</span></label><div class="button-row"><button class="button primary" :disabled="importBusy || !rightsConfirmed || !importContent.trim()"><FileJson :size="16" />{{ importBusy ? '正在匯入…' : '確認並匯入資料' }}</button><span class="small muted">匯入後選擇「合法匯入」來源執行任務</span></div></form></section>
          <div class="info-line"><Info :size="18" /><p>取得正式來源授權後，需先確認能否搜尋其他賣家的商品、欄位、頻率限制、費用及自動化條件，再啟用新來源。登入蝦皮帳號不等於取得自動化權限。</p></div>
        </template>

        <template v-else-if="section === 'history'">
          <section class="panel"><div class="panel-header"><div><h2>任務執行與錯誤紀錄</h2><p>時間以臺灣時區顯示。排程時區：{{ status?.timezone || 'Asia/Taipei' }}</p></div><select v-model="selectedTask" aria-label="依任務篩選紀錄"><option value="">所有任務</option><option v-for="task in tasks" :key="task.id" :value="String(task.id)">{{ task.task_name }}</option></select></div><div v-if="!filteredRuns.length" class="empty-state"><History :size="32" /><h3>尚無執行紀錄</h3><p>手動執行或排程完成後，會在此記錄結果與錯誤。</p></div><div v-else class="run-list"><article v-for="run in filteredRuns" :key="run.id" class="run-item"><span class="run-icon" :class="{ failed: run.status === 'failed' || run.status === 'error' }"><TriangleAlert v-if="run.error_message" :size="20" /><Check v-else-if="run.finished_at" :size="20" /><Clock3 v-else :size="20" /></span><div class="run-details"><div class="run-title"><h3>{{ taskName(run.task_id) }}</h3><span class="tag" :class="run.error_message ? 'tag-red' : run.finished_at ? 'tag-green' : 'tag-blue'">{{ runStatus(run) }}</span></div><p>開始 {{ formatDate(run.started_at) }} · {{ run.finished_at ? `結束 ${formatDate(run.finished_at)}` : '尚未結束' }} · #{{ run.id }}</p><p v-if="isSnapshotTask(run.task_id)">實驗快照重新分析，不代表重新瀏覽或取得新商品。</p><p class="run-ai-summary">AI 新分析 {{ run.ai_new_count ?? 0 }} 次 · 沿用既有分析 {{ run.ai_reused_count ?? 0 }} 筆<span v-if="(run.ai_skipped_count ?? 0) > 0"> · 未呼叫 AI {{ run.ai_skipped_count ?? 0 }} 筆</span></p><div v-if="run.error_message" class="inline-error"><strong>{{ run.error_code || '執行錯誤' }}</strong>：{{ run.error_message }}</div></div><div class="run-numbers"><span><strong>{{ run.found ?? 0 }}</strong>符合商品</span><span><strong>{{ run.new_count ?? 0 }}</strong>新商品</span><span><strong>{{ run.changed_count ?? 0 }}</strong>價格變動</span><span><strong>{{ run.notified_count ?? 0 }}</strong>已通知</span></div></article></div></section>
        </template>

        <template v-else-if="section === 'settings'">
          <form class="settings-grid" @submit.prevent="saveSettings"><section class="panel"><div class="panel-header"><div><h2><Sparkles :size="19" />EagleEye AI</h2><p>支援 OpenAI 相容服務，由伺服器處理參數相容性。</p></div><span class="tag" :class="settings.ai_configured ? 'tag-green' : 'tag-amber'">{{ settings.ai_configured ? '已設定' : '尚未設定' }}</span></div><div class="panel-body"><label class="field">API Base URL<input v-model="settings.OPENAI_BASE_URL" type="url" placeholder="https://api.openai.com/v1" :disabled="!settingsLoaded" /></label><label class="field">模型名稱<input v-model="settings.OPENAI_MODEL_NAME" placeholder="輸入服務支援的模型名稱" :disabled="!settingsLoaded" /></label><label class="field">API Key<input v-model="apiKey" type="password" autocomplete="new-password" placeholder="留白保留現有金鑰" :disabled="!settingsLoaded" /><small>金鑰僅傳送至本系統後端，不回傳到畫面，不儲存在瀏覽器。</small></label><div class="info-line"><ShieldCheck :size="17" /><p>AI 依可取得的證據分析。缺少保固、維修或賣家資訊時，必須標示「資訊不足」。</p></div></div></section><section class="panel"><div class="panel-header"><div><h2><Bell :size="19" />Discord 通知</h2><p>依各任務設定傳送推薦商品或所有符合條件商品。</p></div><span class="tag" :class="settings.discord_configured ? 'tag-green' : 'tag-amber'">{{ settings.discord_configured ? '已設定' : '尚未設定' }}</span></div><div class="panel-body"><label class="field">Discord Webhook URL<input v-model="webhook" type="password" autocomplete="new-password" placeholder="留白保留現有 Webhook" :disabled="!settingsLoaded" /><small>在 Discord 頻道的「整合」建立 Webhook，貼上完整網址。</small></label><ul class="settings-notes"><li>通知包含商品、NT$ 價格、分析理由、風險與原始連結。</li><li>相同商品會去重，降價再次通知由各任務控制。</li><li>模擬資料不等於即時商品。測試時請使用專用頻道。</li><li>儲存設定不會立即傳送通知；請執行任務驗證。</li></ul></div></section><div class="settings-save"><span class="small muted">留白的秘密欄位保留現有設定。請勿將金鑰或 Webhook 提交到 Git。</span><button class="button primary" :disabled="settingsBusy || !settingsLoaded">{{ settingsBusy ? '正在儲存…' : '儲存服務設定' }}</button></div></form>
          <section class="panel prompt-panel"><div class="panel-header"><div><h2>預設 AI 分析提示詞</h2><p>保留商品規格、價格依據、保固、資訊缺口與交易風險分析。各任務可加上補充提示詞。</p></div><Sparkles :size="22" /></div><form class="panel-body" @submit.prevent="savePrompt"><label class="field">base_prompt.txt<textarea v-model="prompt" class="code-input" rows="15" spellcheck="false" :disabled="!promptLoaded || promptBusy" /></label><div class="button-row"><button class="button" :disabled="!promptLoaded || promptBusy || !prompt.trim()">{{ promptBusy ? '正在儲存…' : '儲存預設提示詞' }}</button><span class="small muted">修改後會套用至後續 AI 分析，不會重寫既有結果。</span></div></form></section>
        </template>
        <footer class="page-footer"><span>蝦皮臺灣 AI 商品監控 · 獨立開源工具，非蝦皮官方服務</span><span>資料以來源為準 · 顯示時間 Asia/Taipei</span></footer>
      </main>
    </div>
    <TaskEditor v-if="editor" :task="editor" :providers="status?.providers ?? []" :busy="editorBusy" :error="editorError" :ai-configured="status?.ai_configured ?? false" :timezone="status?.timezone ?? 'Asia/Taipei'" @close="editor = null" @save="saveTask" />
    <dialog ref="historyDialog" class="history-dialog" aria-labelledby="price-history-title" @cancel.prevent="closeHistory"><header class="dialog-header"><div><span class="eyebrow">商品追蹤</span><h2 id="price-history-title">價格歷史</h2></div><button class="icon-button" aria-label="關閉價格歷史" @click="closeHistory"><X :size="20" /></button></header><div class="dialog-content"><h3>{{ selectedProduct?.title }}</h3><p class="small muted">{{ selectedProduct?.product_id }} · {{ sourceName(selectedProduct?.data_source ?? '') }}</p><p v-if="historyBusy" class="empty-state">正在讀取價格紀錄…</p><p v-else-if="historyError" class="inline-error" role="alert">{{ historyError }}</p><div v-else-if="!priceHistory.length" class="empty-state">尚無價格紀錄。</div><ol v-else class="price-history"><li v-for="(point, index) in priceHistory" :key="`${point.observed_at}-${index}`"><span><Clock3 :size="16" />{{ formatDate(point.observed_at) }}</span><strong>{{ formatPrice(point.price_twd) }}</strong><ArrowDown v-if="index > 0 && priceHistory[index - 1] && point.price_twd < priceHistory[index - 1]!.price_twd" :size="17" /></li></ol><p class="small muted">僅記錄系統實際觀察到的價格，不代表市場行情或完整歷史。</p></div></dialog>
  </div>
</template>
