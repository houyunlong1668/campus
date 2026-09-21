// frontend/src/composables/useResource.ts
import { ref, shallowRef, type Ref } from 'vue'
import router from '../router'
import { useAuth } from './useAuth'

export interface Resource<T> {
  data: Ref<T | null>
  loading: Ref<boolean>
  error: Ref<string>
  reload: () => Promise<void>
}

/** 页面数据的唯一出口：组件不发请求（MVP spec 5.6 的边界）。 */
export function useResource<T>(url: string): Resource<T> {
  // shallowRef：整个响应体一次性替换，深层代理既没用又会让泛型 T 退化成 UnwrapRef<T>
  const data = shallowRef<T | null>(null)
  const loading = ref(true)
  const error = ref('')

  async function reload(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const resp = await fetch(url, { credentials: 'include' })
      if (resp.status === 401) {
        // 会话已不可用，再打 logout 没意义：只清本地态并跳登录
        useAuth().signOut()
        router.push({ path: '/login', query: { next: router.currentRoute.value.fullPath } })
        return
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      data.value = (await resp.json()) as T
    } catch {
      error.value = '加载失败，请确认后端已启动后重试'
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, reload }
}
