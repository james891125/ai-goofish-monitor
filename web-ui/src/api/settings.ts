import { http } from '@/lib/http'

export interface NotificationSettings {
  WEBHOOK_URL?: string
  WEBHOOK_METHOD?: string
  WEBHOOK_HEADERS?: string
  WEBHOOK_CONTENT_TYPE?: string
  WEBHOOK_QUERY_PARAMETERS?: string
  WEBHOOK_BODY?: string
  WEBHOOK_URL_SET?: boolean
  WEBHOOK_HEADERS_SET?: boolean
  CONFIGURED_CHANNELS?: string[]
}

export interface NotificationSettingsUpdate {
  WEBHOOK_URL?: string | null
  WEBHOOK_METHOD?: string | null
  WEBHOOK_HEADERS?: string | null
  WEBHOOK_CONTENT_TYPE?: string | null
  WEBHOOK_QUERY_PARAMETERS?: string | null
  WEBHOOK_BODY?: string | null
}

export interface NotificationTestResponse {
  message: string
  results: Record<string, {
    label: string
    success: boolean
    message: string
  }>
}

export interface AiSettings {
  OPENAI_API_KEY?: string
  OPENAI_BASE_URL?: string
  OPENAI_MODEL_NAME?: string
  PROXY_URL?: string
}

export interface RotationSettings {
  ACCOUNT_ROTATION_ENABLED?: boolean
  ACCOUNT_ROTATION_MODE?: string
  ACCOUNT_ROTATION_RETRY_LIMIT?: number
  ACCOUNT_BLACKLIST_TTL?: number
  ACCOUNT_STATE_DIR?: string
  PROXY_ROTATION_ENABLED?: boolean
  PROXY_ROTATION_MODE?: string
  PROXY_POOL?: string
  PROXY_ROTATION_RETRY_LIMIT?: number
  PROXY_BLACKLIST_TTL?: number
}

export interface SystemStatus {
  scraper_running: boolean
  running_task_ids?: number[]
  ai_configured?: boolean
  notification_configured?: boolean
  headless_mode?: boolean
  running_in_docker?: boolean
  login_state_file: {
    exists: boolean
    path: string
  }
  env_file: {
    exists: boolean
    openai_api_key_set: boolean
    openai_base_url_set: boolean
    openai_model_name_set: boolean
    webhook_url_set: boolean
    webhook_headers_set: boolean
  }
  configured_notification_channels?: string[]
}

export async function getNotificationSettings(): Promise<NotificationSettings> {
  return await http('/api/settings/notifications')
}

export async function updateNotificationSettings(settings: NotificationSettingsUpdate): Promise<{ message: string; configured_channels: string[] }> {
  return await http('/api/settings/notifications', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  })
}

export async function testNotificationSettings(
  payload: { channel?: string; settings: NotificationSettingsUpdate }
): Promise<NotificationTestResponse> {
  return await http('/api/settings/notifications/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function getAiSettings(): Promise<AiSettings> {
  return await http('/api/settings/ai')
}

export async function updateAiSettings(settings: AiSettings): Promise<void> {
  await http('/api/settings/ai', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  })
}

export async function getRotationSettings(): Promise<RotationSettings> {
  return await http('/api/settings/rotation')
}

export async function updateRotationSettings(settings: RotationSettings): Promise<void> {
  await http('/api/settings/rotation', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  })
}

export async function testAiSettings(settings: AiSettings): Promise<{ success: boolean; message: string; response?: string }> {
  return await http('/api/settings/ai/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  })
}

export async function getSystemStatus(): Promise<SystemStatus> {
  return await http('/api/settings/status')
}

export async function updateLoginState(content: string): Promise<{ message: string }> {
  return await http('/api/login-state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content })
  })
}

export async function deleteLoginState(): Promise<{ message: string }> {
  return await http('/api/login-state', { method: 'DELETE' })
}
