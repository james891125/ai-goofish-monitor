import type { BrowserImportPayload, BrowserRequest, Provider, ShopeeTask } from '../api/shopee'

export const taiwanRegions = ['臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市', '基隆市', '新竹市', '嘉義市', '新竹縣', '苗栗縣', '彰化縣', '南投縣', '雲林縣', '嘉義縣', '屏東縣', '宜蘭縣', '花蓮縣', '臺東縣', '澎湖縣', '金門縣', '連江縣']
export const scheduleOptions = [
  { value: '', label: '僅手動執行' },
  { value: '*/15 * * * *', label: '每 15 分鐘' },
  { value: '*/30 * * * *', label: '每 30 分鐘' },
  { value: '0 * * * *', label: '每小時' },
  { value: 'custom', label: '自訂 Cron' },
]
export function newTask(): ShopeeTask {
  return { task_name: '', enabled: true, keyword: '', provider: 'mock', decision_mode: 'ai', description: '', analyze_images: false, min_price: null, max_price: null, max_items: 50, max_pages: 3, category: null, condition: null, region: null, seller_type: null, exclude_keywords: [], exclude_ads: false, cron: null, notify: 'recommended', notify_price_drop: false, custom_prompt: '' }
}
export function sampleTask(kind: 'rtx' | 'mac'): ShopeeTask {
  const base = newTask()
  return kind === 'rtx' ? { ...base, task_name: 'RTX 5070 Ti 二手監控', keyword: 'RTX 5070 Ti', min_price: 15000, max_price: 25000, cron: '*/30 * * * *', description: '確認顯示卡型號、記憶體容量、保固及維修紀錄，辨識交易風險。價格僅為示範範圍，並非市場行情。', exclude_keywords: ['空盒', '散熱器'] } : { ...base, task_name: 'Mac mini M4 二手監控', keyword: 'Mac mini M4', cron: '0 * * * *', description: '確認 M4 晶片、RAM、SSD、保固及商品狀態。缺少的規格或賣家資訊請標示資訊不足，不推測。', exclude_keywords: ['配件', '空盒', '保護套', '支架'] }
}
export function validateTask(task: ShopeeTask, provider?: Provider): string[] {
  const errors: string[] = []
  if (!task.task_name.trim()) errors.push('請輸入任務名稱。')
  if (!task.keyword.trim()) errors.push('請輸入搜尋關鍵字。')
  if (task.decision_mode === 'ai' && !task.description.trim()) errors.push('AI 分析模式必須填寫詳細購買需求。')
  if (!provider?.available) errors.push('請選擇目前可使用的資料來源。')
  if (task.min_price !== null && (!Number.isFinite(task.min_price) || task.min_price < 0)) errors.push('最低價格必須為零或正數。')
  if (task.max_price !== null && (!Number.isFinite(task.max_price) || task.max_price < 0)) errors.push('最高價格必須為零或正數。')
  if (task.min_price !== null && task.max_price !== null && task.min_price > task.max_price) errors.push('最高價格不能低於最低價格。')
  if (!Number.isInteger(task.max_items) || task.max_items < 1 || task.max_items > 500) errors.push('搜尋筆數必須是 1 至 500 的整數。')
  if (!Number.isInteger(task.max_pages) || task.max_pages < 1 || task.max_pages > 20) errors.push('搜尋頁數必須是 1 至 20 的整數。')
  if (task.cron && task.cron.trim().split(/\s+/).length !== 5) errors.push('Cron 必須包含五個欄位：分、時、日、月、星期。')
  if (task.provider === 'browser_experiment') {
    if (task.decision_mode !== 'ai') errors.push('實驗瀏覽快照保留 AI 分析，不支援關鍵字取代 AI。')
    if (task.max_items > 5) errors.push('實驗瀏覽快照每次最多分析 5 筆。')
    if (task.max_pages !== 1) errors.push('實驗瀏覽快照固定為 1 頁，不會自動翻頁。')
    if (task.cron !== null) errors.push('實驗瀏覽快照只能手動重新分析，不支援排程。')
  }
  return errors
}
export function sanitizeCapabilities(task: ShopeeTask, provider?: Provider): ShopeeTask {
  const cap = provider?.capabilities ?? {}
  return { ...task, category: cap.category ? task.category : null, condition: cap.condition ? task.condition : null, region: cap.region ? task.region : null, seller_type: cap.seller_type ? task.seller_type : null, exclude_ads: cap.ads ? task.exclude_ads : false }
}
export function formatPrice(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `NT$${new Intl.NumberFormat('zh-TW', { maximumFractionDigits: 2 }).format(value)}` : '未提供價格'
}
export function formatDate(value: string | null | undefined): string {
  if (!value) return '尚未記錄'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '無效時間' : new Intl.DateTimeFormat('zh-TW', { timeZone: 'Asia/Taipei', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date)
}
export function scheduleLabel(cron: string | null): string {
  return scheduleOptions.find(option => option.value === (cron ?? ''))?.label ?? `自訂 ${cron}`
}
export function safeProductUrl(value: string | undefined): string | undefined {
  if (!value) return undefined
  try { const url = new URL(value); return url.protocol === 'https:' && ['shopee.tw', 'www.shopee.tw'].includes(url.hostname) && !url.username && !url.password && (!url.port || url.port === '443') ? url.href : undefined } catch { return undefined }
}
export function safeImageUrl(value: string | undefined): string | undefined {
  if (!value) return undefined
  try { const url = new URL(value); return url.protocol === 'https:' && (url.hostname.endsWith('.susercontent.com') || url.hostname.endsWith('.shopee.tw')) && !url.username && !url.password && (!url.port || url.port === '443') ? url.href : undefined } catch { return undefined }
}
export function parseImport(content: string): unknown[] {
  const parsed: unknown = JSON.parse(content)
  const products: unknown = Array.isArray(parsed) ? parsed : typeof parsed === 'object' && parsed !== null && 'products' in parsed ? parsed.products : null
  if (!Array.isArray(products) || !products.length) throw new Error('請提供非空的商品陣列，或包含 products 陣列的 JSON。')
  if (products.length > 500) throw new Error('每次最多匯入 500 筆商品。')
  return products
}

// A collector request contains public product URLs only, never login/session data.
// Reject ambiguous URL syntax before URL() has a chance to normalize it.
export function browserProductUrl(value: string): string | undefined {
  const prefix = /^https:\/\/(?:www\.)?shopee\.tw(?::443)?(?=\/)/i
  if (!prefix.test(value) || /[\s\\\u0000-\u001f\u007f]/.test(value)) return undefined
  try {
    const url = new URL(value)
    if (url.username || url.password || url.port) return undefined
    const rawPath = value.replace(prefix, '').split(/[?#]/)[0] ?? ''
    if (/%(?:2f|5c|3f|23|2e)/i.test(rawPath)) return undefined
    const path = decodeURIComponent(rawPath)
    if (/[\u0000-\u001f\u007f]/.test(path) || path !== decodeURIComponent(url.pathname)) return undefined
    const product = path.match(/^\/product\/([1-9]\d*)\/([1-9]\d*)\/?$/) ?? path.match(/^\/[^/\\?#\s]+-i\.([1-9]\d*)\.([1-9]\d*)\/?$/)
    return product ? `https://shopee.tw/product/${product[1]}/${product[2]}` : undefined
  } catch { return undefined }
}

export function buildBrowserRequest(keyword: string, urlLines: string, intervalSeconds: number, maxItems: number): BrowserRequest {
  const trimmedKeyword = keyword.trim()
  const urls = urlLines.split(/\r?\n/).map(value => value.trim()).filter(Boolean)
  if (Boolean(trimmedKeyword) === Boolean(urls.length)) throw new Error('請擇一填寫搜尋關鍵字或商品網址清單，不能同時填寫。')
  if (trimmedKeyword.length > 200 || /[\u0000-\u001f\u007f]/.test(trimmedKeyword)) throw new Error('搜尋關鍵字最多 200 字，且不能包含換行或控制字元。')
  if (urls.length > 5) throw new Error('商品網址清單限 1 至 5 筆，一行一個網址。')
  if (!Number.isInteger(intervalSeconds) || intervalSeconds < 60 || intervalSeconds > 300) throw new Error('瀏覽間隔必須是 60 至 300 秒的整數。')
  if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > 5) throw new Error('最多收集筆數必須是 1 至 5 的整數。')
  const normalized = urls.map((value, index) => {
    const url = browserProductUrl(value)
    if (!url) throw new Error(`第 ${index + 1} 行不是有效的臺灣蝦皮商品網址。請使用 HTTPS 商品連結；不接受短網址、搜尋頁或登入頁。`)
    return url
  })
  if (new Set(normalized).size !== normalized.length) throw new Error('商品網址不可重複。')
  return { keyword: trimmedKeyword || null, urls: normalized, interval_seconds: intervalSeconds, max_items: maxItems }
}

export function buildBrowserImport(content: string, rightsConfirmed: boolean, riskConfirmed: boolean): BrowserImportPayload {
  if (!rightsConfirmed || !riskConfirmed) throw new Error('請分別確認資料使用權與實驗瀏覽風險後，才能匯入快照。')
  const products = parseImport(content)
  if (products.length > 5) throw new Error('實驗瀏覽快照每次最多匯入 5 筆商品。')
  if (products.some(product => typeof product !== 'object' || product === null || Array.isArray(product))) throw new Error('每一筆快照商品都必須是 JSON 物件。')
  return { products, rights_confirmed: true, risk_confirmed: true }
}
