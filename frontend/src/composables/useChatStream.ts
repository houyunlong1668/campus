import { ref } from 'vue'
import { createSSEParser } from '../lib/sse'
import type {
  ChatRequest, DoneEvent, ErrorEvent, NavCardEvent, TokenEvent, ToolCallEvent,
} from '../types'
import type { NavCard } from '../types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  toolCall: { name: string; ok: boolean; latencyMs: number } | null
  navCard: NavCard | null
  error: string | null
}

export function useChatStream() {
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const pendingCard = ref<NavCard | null>(null)
  const sessionId = crypto.randomUUID()
  let controller: AbortController | null = null

  async function send(text: string) {
    if (streaming.value) return
    messages.value.push({ id: crypto.randomUUID(), role: 'user', text, toolCall: null, navCard: null, error: null })
    messages.value.push({
      id: crypto.randomUUID(), role: 'assistant', text: '',
      toolCall: null, navCard: null, error: null,
    })
    // 必须取数组里的代理再改：直接改 push 前的原始对象不会触发重渲染
    const assistant = messages.value[messages.value.length - 1]
    streaming.value = true
    controller = new AbortController()

    const body: ChatRequest = { message: text, session_id: sessionId }
    try {
      const resp = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
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

  return { messages, streaming, pendingCard, sessionId, send, abort }
}
