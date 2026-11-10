import { http } from '@/lib/http'

export interface Provider {
  id: string
  name: string
  available: boolean
  authorization_status: string
  expires_at: string | null
  capabilities: Partial<Record<'keyword' | 'price' | 'category' | 'condition' | 'region' | 'seller_type' | 'ads', boolean>>
}
export interface SourceStatus {
  release_status: string
  message: string
  providers: Provider[]
  ai_configured: boolean
  discord_configured: boolean
  timezone: string
}
export interface ShopeeTask {
  id?: number
  task_name: string
  enabled: boolean
  keyword: string
  provider: string
  decision_mode: 'keyword' | 'ai'
  description: string
  analyze_images: boolean
  min_price: number | null
  max_price: number | null
  max_items: number
  max_pages: number
  category: string | null
  condition: 'new' | 'used' | null
  region: string | null
  seller_type: 'personal' | 'business' | null
  exclude_keywords: string[]
  exclude_ads: boolean
  cron: string | null
  notify: 'recommended' | 'all'
  notify_price_drop: boolean
  custom_prompt: string
  is_running?: boolean
  next_run_at?: string | null
}
export interface Product {
  platform: string
  product_id: string
  title: string
  price_twd: number
  original_price_twd: number | null
  condition: string | null
  description: string
  images: string[]
  images_allowed?: boolean
  product_url: string
  seller: { seller_id: string | null; name: string | null; rating: number | null; review_count: number | null; location: string | null; verified_type: string | null }
  listed_at: string | null
  collected_at: string
  data_source: string
  data_quality: string
  task_id?: number
  analysis?: Record<string, unknown> | null
  is_new?: boolean
  price_changed?: boolean
  last_seen?: string
}
export interface Run {
  id: number
  task_id: number
  started_at: string
  finished_at: string | null
  status: string
  found: number
  new_count: number
  changed_count: number
  notified_count: number
  error_code?: string | null
  error_message?: string | null
}
export interface Settings {
  OPENAI_BASE_URL: string
  OPENAI_MODEL_NAME: string
  OPENAI_API_KEY?: string
  DISCORD_WEBHOOK_URL?: string
  ai_configured?: boolean
  discord_configured?: boolean
}
export interface PricePoint { price_twd: number; observed_at: string }

function write<T>(url: string, method: string, payload?: unknown): Promise<T> {
  return http(url, { method, headers: { 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload) })
}
export const shopeeApi = {
  status: (): Promise<SourceStatus> => http('/api/shopee/status'),
  tasks: (): Promise<ShopeeTask[]> => http('/api/shopee/tasks'),
  saveTask: (task: ShopeeTask): Promise<ShopeeTask> => {
    const { is_running: _running, next_run_at: _nextRun, ...payload } = task
    return write(`/api/shopee/tasks${task.id === undefined ? '' : `/${task.id}`}`, task.id === undefined ? 'POST' : 'PUT', payload)
  },
  deleteTask: (id: number): Promise<unknown> => write(`/api/shopee/tasks/${id}`, 'DELETE'),
  runTask: (id: number): Promise<unknown> => write(`/api/shopee/tasks/${id}/run`, 'POST'),
  products: (taskId?: number): Promise<Product[]> => http('/api/shopee/products', { params: { task_id: taskId } }),
  runs: (taskId?: number): Promise<Run[]> => http('/api/shopee/runs', { params: { task_id: taskId } }),
  history: (id: string, taskId?: number, source?: string): Promise<PricePoint[]> => http(`/api/shopee/products/${encodeURIComponent(id)}/history`, { params: { task_id: taskId, source } }),
  importProducts: (products: unknown[]): Promise<{ imported: number }> => write('/api/shopee/import', 'POST', { products, rights_confirmed: true }),
  settings: (): Promise<Settings> => http('/api/shopee/settings'),
  saveSettings: (settings: Settings): Promise<unknown> => write('/api/shopee/settings', 'PUT', settings),
  prompt: (): Promise<{ filename: string; content: string }> => http('/api/prompts/base_prompt.txt'),
  savePrompt: (content: string): Promise<unknown> => write('/api/prompts/base_prompt.txt', 'PUT', { content }),
}
