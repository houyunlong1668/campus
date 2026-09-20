import { ref } from 'vue'
import type { StudentInfo } from '../types'

export type AuthStatus = 'unknown' | 'authed' | 'anonymous'
export type LoginResult =
  | { ok: true }
  | { ok: false; code: 'bad_credentials' | 'too_many_attempts' | 'network'; message: string }

// 模块级：登录态是全站状态，路由守卫、顶栏与聊天面板共用一份
const user = ref<StudentInfo | null>(null)
const status = ref<AuthStatus>('unknown')

async function readError(resp: Response): Promise<LoginResult> {
  const code = resp.status === 429 ? 'too_many_attempts' : 'bad_credentials'
  let message = '学号或密码不正确'
  try {
    const body = await resp.json()
    if (body?.detail?.message) message = body.detail.message
  } catch {
    // 非 JSON 响应保留默认文案
  }
  return { ok: false, code, message }
}

export function useAuth() {
  async function bootstrap(): Promise<void> {
    try {
      const resp = await fetch('/auth/me', { credentials: 'include' })
      if (resp.ok) {
        user.value = (await resp.json()) as StudentInfo
        status.value = 'authed'
      } else {
        user.value = null
        status.value = 'anonymous'
      }
    } catch {
      user.value = null
      status.value = 'anonymous'
    }
  }

  async function login(studentId: string, password: string): Promise<LoginResult> {
    let resp: Response
    try {
      resp = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ student_id: studentId, password }),
      })
    } catch {
      return { ok: false, code: 'network', message: '连不上服务器，请确认后端已启动' }
    }

    if (!resp.ok) {
      const result = await readError(resp)
      user.value = null
      status.value = 'anonymous'
      return result
    }

    user.value = (await resp.json()) as StudentInfo
    status.value = 'authed'
    return { ok: true }
  }

  async function logout(): Promise<void> {
    await fetch('/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {})
    signOut()
  }

  /** 只清本地状态：供 /chat 收到 401 时调用，服务端会话此时已不可用 */
  function signOut(): void {
    user.value = null
    status.value = 'anonymous'
  }

  return { user, status, bootstrap, login, logout, signOut }
}
