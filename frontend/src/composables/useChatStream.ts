import { ref } from 'vue'
import { createSSEParser } from '../lib/sse'
import { useAuth } from './useAuth'
import type {
  ChatRequest, ClarifyEvent, DoneEvent, ErrorEvent, NavCardEvent, SqlResultEvent,
  TokenEvent, ToolCallEvent,
} from '../types'
import type { NavCard } from '../types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  toolCall: { name: string; ok: boolean; latencyMs: number } | null
  navCard: NavCard | null
  clarify: ClarifyEvent | null
  sqlResult: SqlResultEvent | null
  error: string | null
}

// 模块级状态：悬浮球收起会卸载 ChatBox，会话历史与在途流必须活过它
const messages = ref<ChatMessage[]>([])
const streaming = ref(false)
const pendingCard = ref<NavCard | null>(null)
let controller: AbortController | null = null

export function useChatStream() {
  async function send(text: string) {
    if (streaming.value) return
    messages.value.push({
      id: crypto.randomUUID(), role: 'user', text,
      toolCall: null, navCard: null, clarify: null, sqlResult: null, error: null,
    })
    messages.value.push({
      id: crypto.randomUUID(), role: 'assistant', text: '',
      toolCall: null, navCard: null, clarify: null, sqlResult: null, error: null,
    })
    // 必须取数组里的代理再改：直接改 push 前的原始对象不会触发重渲染
    const assistant = messages.value[messages.value.length - 1]
    streaming.value = true
    controller = new AbortController()

    const body: ChatRequest = { message: text }
    try {
      const resp = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        credentials: 'include',
        signal: controller.signal,
      })
      if (resp.status === 401) {
        // 会话过期：本地登录态即刻作废并回登录页，不把这一步留给用户猜。
        // router 用动态 import：静态引入会把 createWebHistory() 拖进 Node 测试环境。
        const { signOut } = useAuth()
        signOut()
        assistant.error = '登录已过期，请重新登录'
        const { default: router } = await import('../router')
        await router.push({ path: '/login', query: { next: router.currentRoute.value.fullPath } })
        return
      }
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)

      const parser = createSSEParser()
      const reader = resp.body.getReader()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        for (const frame of parser.feed(value)) {
          if (frame.event === 'token') {
            assistant.text += (JSON.parse(frame.data) as TokenEvent).text
          } else if (frame.event === 'tool_call') {
            const e = JSON.parse(frame.data) as ToolCallEvent
            assistant.toolCall = { name: e.name, ok: e.ok, latencyMs: e.latency_ms }
          } else if (frame.event === 'nav_card') {
            const e = JSON.parse(frame.data) as NavCardEvent
            assistant.navCard = e
            pendingCard.value = e
          } else if (frame.event === 'clarify') {
            assistant.clarify = JSON.parse(frame.data) as ClarifyEvent
          } else if (frame.event === 'sql_result') {
            assistant.sqlResult = JSON.parse(frame.data) as SqlResultEvent
          } else if (frame.event === 'done') {
            void (JSON.parse(frame.data) as DoneEvent) // steps 留作操作日志面板数据源
          } else if (frame.event === 'error') {
            const e = JSON.parse(frame.data) as ErrorEvent
            assistant.error = `${e.code}: ${e.message}`
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        assistant.error = (err as Error).message
      }
    } finally {
      streaming.value = false
      controller = null
    }
  }

  function abort() {
    controller?.abort()
  }

  return { messages, streaming, pendingCard, send, abort }
}
