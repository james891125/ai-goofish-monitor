<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { ShoppingBag, ArrowRight, LockKeyhole } from 'lucide-vue-next'
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')
const { login } = useAuth()
const router = useRouter()
const route = useRoute()
async function submit() {
  if (busy.value) return
  if (!username.value.trim() || !password.value) { error.value = '請輸入管理員帳號及密碼。'; return }
  busy.value = true
  error.value = ''
  try {
    if (await login(username.value.trim(), password.value)) {
      password.value = ''
      const redirect = typeof route.query.redirect === 'string' && /^\/(?!\/)/.test(route.query.redirect) ? route.query.redirect : '/tasks'
      await router.push(redirect)
    } else error.value = '無法登入。請確認帳號、密碼及伺服器連線。'
  } finally { busy.value = false }
}
</script>
<template>
  <main class="login-screen">
    <section class="login-story">
      <div class="brand"><span class="brand-icon"><ShoppingBag :size="25" /></span><span>蝦皮臺灣<span class="brand-sub">AI 商品監控</span></span></div>
      <div><span class="eyebrow">更有依據的購物決策</span><h1>找到合適的商品，<br>留住值得注意的變化。</h1><p>關鍵字篩選、價格紀錄與 AI 分析。<br>從每一筆有來源的資訊開始。</p></div>
      <p class="login-footnote">獨立開源工具，非蝦皮官方服務。</p>
    </section>
    <section class="login-panel">
      <div class="login-form">
        <span class="login-lock"><LockKeyhole :size="23" /></span><h2>登入監控中心</h2><p class="muted">使用系統管理員帳號登入，不需蝦皮帳號。</p>
        <div class="notice compact"><strong>等待資料來源授權</strong><p>目前提供模擬測試與合法資料匯入，尚未開放全站即時搜尋。</p></div>
        <form @submit.prevent="submit">
          <label class="field">管理員帳號<input v-model="username" autocomplete="username" required placeholder="輸入帳號" /></label>
          <label class="field">密碼<input v-model="password" type="password" autocomplete="current-password" required placeholder="輸入密碼" /></label>
          <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
          <button class="button primary login-submit" :disabled="busy">{{ busy ? '正在登入…' : '登入' }}<ArrowRight :size="17" /></button>
        </form>
        <p class="small muted">憑證僅用於本系統驗證。請由部署管理員設定帳密，並使用 HTTPS 保護連線。</p>
      </div>
    </section>
  </main>
</template>
