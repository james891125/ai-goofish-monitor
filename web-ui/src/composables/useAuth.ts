import { ref, computed } from 'vue'

// Global State
const username = ref<string | null>(localStorage.getItem('auth_username'))
const isLoggedIn = ref(localStorage.getItem('auth_logged_in') === 'true')

export function useAuth() {

  const isAuthenticated = computed(() => isLoggedIn.value)

  function setAuthenticated(user: string) {
    username.value = user
    isLoggedIn.value = true

    localStorage.setItem('auth_username', user)
    localStorage.setItem('auth_logged_in', 'true')

  }

  async function logout() {
    try { await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' }) } catch { /* Clear local session even when the server is unreachable. */ }
    username.value = null
    isLoggedIn.value = false
    localStorage.removeItem('auth_username')
    localStorage.removeItem('auth_logged_in')


    // A full navigation also clears in-memory data from the previous session.
    window.location.assign('/login')
  }

  async function login(user: string, pass: string): Promise<boolean> {
    try {
      const response = await fetch('/auth/status', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username: user, password: pass }),
      })

      if (response.ok) {
        setAuthenticated(user)
        return true
      } else {
        return false
      }
    } catch (e) {
      console.error('Login error', e)
      return false
    }
  }

  return {
    username,
    isAuthenticated,
    login,
    logout
  }
}
