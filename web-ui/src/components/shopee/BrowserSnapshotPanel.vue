<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, FileJson, Info, TriangleAlert } from 'lucide-vue-next'
import { shopeeApi } from '@/api/shopee'
import { buildBrowserImport, buildBrowserRequest } from '@/lib/shopee'

const props = defineProps<{ available: boolean }>()
const emit = defineEmits<{ imported: [count: number] }>()
const keyword = ref('')
const urls = ref('')
const intervalSeconds = ref(120)
const maxItems = ref(5)
const downloadStatus = ref('')
const downloadError = ref('')
const importContent = ref('')
const rightsConfirmed = ref(false)
const riskConfirmed = ref(false)
const importBusy = ref(false)
const readingFile = ref(false)
const importError = ref('')
let fileRequest = 0
const fileLimit = 5 * 1024 * 1024
const installCommand = String.raw`.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt`
const collectCommand = String.raw`.\.venv\Scripts\python.exe scripts/browser_collect.py --request browser-request.json --output browser-results.json --channel msedge`
const requestState = computed(() => {
  try { return { request: buildBrowserRequest(keyword.value, urls.value, intervalSeconds.value, maxItems.value), error: '' } }
  catch (cause) { return { request: null, error: cause instanceof Error ? cause.message : '請檢查收集設定。' } }
})
const requestPreview = computed(() => requestState.value.request ? JSON.stringify(requestState.value.request, null, 2) : '')
const hasRequestInput = computed(() => !!keyword.value.trim() || !!urls.value.trim())
const importDisabled = computed(() => importBusy.value || readingFile.value || !props.available)

watch([keyword, urls, intervalSeconds, maxItems], () => { downloadStatus.value = ''; downloadError.value = '' }, { flush: 'sync' })
// Confirmation belongs to these exact bytes, not a previously selected file.
watch(importContent, () => { rightsConfirmed.value = false; riskConfirmed.value = false; importError.value = '' }, { flush: 'sync' })
onBeforeUnmount(() => { fileRequest++ })

function downloadRequest() {
  downloadStatus.value = ''; downloadError.value = ''
  if (!requestState.value.request) { downloadError.value = requestState.value.error; return }
  let objectUrl: string | undefined
  const anchor = document.createElement('a')
  try {
    objectUrl = URL.createObjectURL(new Blob([requestPreview.value + '\n'], { type: 'application/json;charset=utf-8' }))
    anchor.href = objectUrl
    anchor.download = 'browser-request.json'
    document.body.appendChild(anchor)
    anchor.click()
    downloadStatus.value = '已送出 browser-request.json 下載。請將檔案放到專案根目錄，再自行執行下方指令。瀏覽器尚未啟動。'
  } catch { downloadError.value = '無法下載設定檔。可複製下方 JSON 並以 browser-request.json 儲存。' }
  finally {
    anchor.remove()
    if (objectUrl) { const url = objectUrl; setTimeout(() => URL.revokeObjectURL(url), 1000) }
  }
}
async function readFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || importBusy.value) return
  const request = ++fileRequest
  rightsConfirmed.value = false; riskConfirmed.value = false; importError.value = ''
  if (file.size > fileLimit) { importError.value = 'JSON 檔案不可超過 5 MB。'; input.value = ''; return }
  readingFile.value = true
  try { const content = await file.text(); if (request === fileRequest) importContent.value = content }
  catch { if (request === fileRequest) importError.value = '無法讀取快照檔案，請檢查檔案權限或貼上 JSON。' }
  finally { if (request === fileRequest) readingFile.value = false; input.value = '' }
}
async function importSnapshots() {
  if (importDisabled.value) return
  importError.value = ''
  try {
    if (new Blob([importContent.value]).size > fileLimit) throw new Error('JSON 內容不可超過 5 MB。')
    const payload = buildBrowserImport(importContent.value, rightsConfirmed.value, riskConfirmed.value)
    importBusy.value = true
    const result = await shopeeApi.importBrowserProducts(payload)
    importContent.value = ''
    rightsConfirmed.value = false; riskConfirmed.value = false
    emit('imported', result.imported)
  } catch (cause) {
    importError.value = cause instanceof SyntaxError ? 'JSON 格式不正確，請檢查引號、逗號及括號。' : cause instanceof Error ? cause.message : '快照匯入未完成，請檢查執行紀錄。'
  } finally { importBusy.value = false }
}
</script>

<template>
  <section class="panel browser-snapshot-panel" aria-labelledby="browser-snapshot-title">
    <header class="panel-header wrap">
      <div><h2 id="browser-snapshot-title">實驗瀏覽快照（手動更新）</h2><p>選用功能：本機手動執行收集工具，再將結果匯入分析。</p></div>
      <span class="tag tag-amber">實驗功能 · 未驗證平台授權</span>
    </header>
    <div class="panel-body">
      <div class="notice snapshot-risk" role="note"><TriangleAlert :size="21" /><div><strong>請先閱讀自動化條款與帳號風險</strong><p>使用自己的帳號登入、少量收集、放慢速度或模仿人工操作，都不代表已取得蝦皮的自動化存取權限，也不能保證不會被限制或停權。請先確認使用條款及所需授權；若無適用權限，請勿執行收集。</p><p>遇到驗證碼、反機器人挑戰、HTTP 403 或 429 時立即停止，不會自動重試、繞過或切換帳號。整體發行狀態仍為「等待資料來源授權」，尚未完成真實蝦皮網站驗證。</p></div></div>
      <ol class="snapshot-steps">
        <li>建立設定檔：輸入一個關鍵字，或 1 至 5 個商品網址。</li>
        <li>自行執行本機工具：開啟一般可見的 Edge 瀏覽器，必要時由您手動登入暫存工作階段；不匯出 Cookie、不保存登入狀態。</li>
        <li>匯入快照後保留 AI 分析，以最多 5 筆與快取重用控制 Token；網頁內執行任務不會發現新商品。</li>
      </ol>
      <form class="snapshot-section" @submit.prevent="downloadRequest">
        <h3>1. 建立收集設定檔</h3>
        <p class="snapshot-description">以下兩種輸入擇一。關鍵字只讀取公開搜尋結果第一頁最多 5 個可見商品連結；不翻頁。逐一瀏覽商品，不並行。</p>
        <div class="form-grid">
          <label class="field">收集關鍵字<input v-model="keyword" maxlength="200" placeholder="例如 RTX 5070 Ti（與網址清單擇一）" autocomplete="off" /><small>只會寫入設定檔，不會從此網頁送出搜尋。</small></label>
          <label class="field">商品網址清單<textarea v-model="urls" rows="4" placeholder="https://shopee.tw/product/123/456&#10;https://shopee.tw/商品名稱-i.123.789" spellcheck="false" /><small>1 至 5 筆，一行一個完整的 shopee.tw 商品連結。追蹤參數會在本機移除，不接受短網址。</small></label>
          <label class="field">逐筆瀏覽間隔（秒）<input v-model.number="intervalSeconds" type="number" min="60" max="300" step="1" required /><small>60 至 300 秒。降低頻率不代表已獲授權或能避免限制。</small></label>
          <label class="field">最多收集筆數<input v-model.number="maxItems" type="number" min="1" max="5" step="1" required /><small>1 至 5 筆。網址多於上限時，只處理清單前幾筆。</small></label>
        </div>
        <p v-if="requestState.error" :class="hasRequestInput ? 'inline-error' : 'small muted'" aria-live="polite">{{ requestState.error }}</p>
        <div class="button-row snapshot-actions"><button class="button" :disabled="!requestState.request"><Download :size="16" />下載 browser-request.json</button><span class="small muted">僅下載設定，不會安裝程式或啟動瀏覽器。</span></div>
        <p v-if="downloadStatus" class="snapshot-feedback" role="status">{{ downloadStatus }}</p>
        <p v-if="downloadError" class="inline-error" role="alert">{{ downloadError }}</p>
        <details v-if="requestPreview" class="snapshot-preview"><summary>檢查設定 JSON</summary><pre>{{ requestPreview }}</pre></details>
      </form>
      <section class="snapshot-section" aria-labelledby="browser-command-title">
        <h3 id="browser-command-title">2. 在 Windows 手動執行</h3>
        <p class="snapshot-description">先完成專案的一般本機啟動設定，再將下載的設定檔放在專案根目錄。在該目錄開啟 PowerShell，首次使用時自行安裝選用套件：</p>
        <pre class="snapshot-command" aria-label="安裝選用瀏覽套件指令">{{ installCommand }}</pre>
        <p class="snapshot-description">確認授權與風險後，使用已安裝的 Microsoft Edge 執行。依終端機提示確認及手動登入；完成後關閉暫存瀏覽器：</p>
        <pre class="snapshot-command" aria-label="收集瀏覽快照指令">{{ collectCommand }}</pre>
        <p class="snapshot-description">再次收集時，若 browser-results.json 已存在，工具會停止以保留原檔。請改用新的輸出檔名，例如 --output browser-results-2.json，再匯入該新檔。請勿同時執行多份收集工具。</p>
        <div class="info-line"><Info :size="17" /><p>這些指令只供您複製，不會自動執行。驗證碼、封鎖或登入失敗時請停止，勿反覆執行。輸出 browser-results.json 為當次可見文字快照，可能缺少價格或規格；不收集圖片、不推測缺漏欄位。</p></div>
      </section>
      <form class="snapshot-section" @submit.prevent="importSnapshots">
        <h3>3. 匯入收集結果</h3>
        <p class="snapshot-description">選擇 browser-results.json 或貼上內容，接受商品陣列或 { products: [...] }。最多 5 筆、5 MB；不接受圖片、帳密、Cookie 或存取權杖。</p>
        <p v-if="!available" class="inline-error" role="alert">目前後端未提供實驗快照匯入功能，請確認前後端使用相同版本。</p>
        <label class="file-input">選擇瀏覽快照 JSON 檔案<input type="file" accept="application/json,.json" :disabled="importDisabled" @change="readFile" /></label>
        <label class="field">瀏覽快照 JSON<textarea v-model="importContent" class="code-input" rows="8" spellcheck="false" placeholder='{"source":"browser_experiment","products":[...]}' :disabled="importDisabled" required /></label>
        <label class="check rights-check"><input v-model="rightsConfirmed" type="checkbox" required :disabled="importDisabled" /><span>我確認有權取得及匯入這份快照中的商品文字資料，並遵守資料來源的使用條款與授權條件。</span></label>
        <label class="check rights-check"><input v-model="riskConfirmed" type="checkbox" required :disabled="importDisabled" /><span>我了解這是尚未驗證平台授權的實驗功能；自己的帳號與低頻瀏覽不等於自動化權限，可能遭遇存取限制或停權，遇到驗證碼、403 或 429 必須停止且不重試。</span></label>
        <p v-if="importError" class="inline-error" role="alert">{{ importError }}</p>
        <div class="button-row snapshot-actions"><button class="button primary" :disabled="importDisabled || !rightsConfirmed || !riskConfirmed || !importContent.trim()"><FileJson :size="16" />{{ importBusy ? '正在匯入快照…' : readingFile ? '正在讀取檔案…' : '確認並匯入實驗快照' }}</button></div>
        <p class="snapshot-description">匯入後，請選擇「實驗瀏覽快照（手動更新）」建立 AI 任務，並填寫購買需求。未變動的商品與分析條件可沿用既有 AI 結果，以減少重複 Token，不以關鍵字取代 AI。未收集圖片的部分須標示證據不足。執行不會再次瀏覽網站；要取得新商品或更新價格，需重新執行工具並匯入。</p>
      </form>
    </div>
  </section>
</template>

<style scoped>
.browser-snapshot-panel { margin-bottom: 24px; }
.snapshot-risk p { color: #87642d; font-size: 12px; }
.snapshot-steps { padding-left: 22px; font-size: 12px; color: #66727e; line-height: 2; list-style: decimal; }
.snapshot-section { border-top: 1px solid var(--line); margin-top: 24px; padding-top: 23px; }
.snapshot-section h3 { margin-bottom: 12px; }
.snapshot-description { color: #7e8a96; font-size: 11px; margin: 12px 0 18px; }
.snapshot-actions { margin-top: 16px; }
.snapshot-command, .snapshot-preview pre { max-width: 100%; white-space: pre-wrap; overflow-wrap: anywhere; padding: 15px 17px; background: #f5f7fa; color: #455867; border: 1px solid var(--line); border-radius: 7px; font: 12px/1.9 Consolas, monospace; margin-bottom: 18px; }
.snapshot-feedback { margin-top: 12px; color: #398453; font-size: 12px; }
.snapshot-preview { margin-top: 15px; color: #72818f; font-size: 12px; }
.snapshot-preview summary { cursor: pointer; margin-bottom: 10px; }
</style>
