import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChatStream } from '../src/composables/useChatStream'

const enc = (s: string) => new TextEncoder().encode(s)

function stubStream(frames: string[]) {
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (const f of frames) c.enqueue(enc(f))
      c.close()
    },
  })
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body })))
}

afterEach(() => vi.unstubAllGlobals())

describe('useChatStream', () => {
  it('SSE 事件落到响应式代理上，助手消息随流更新', async () => {
    stubStream([
      'event: tool_call\ndata: {"name":"resolve_page","args":{},"ok":true,"error":null,"latency_ms":23}\n\n',
      'event: token\ndata: {"text":"已为你找"}\n\n',
      'event: token\ndata: {"text":"到课表页"}\n\n',
      'event: nav_card\ndata: {"path":"/academic/schedule","title":"课表查询","reason":"最匹配"}\n\n',
      'event: done\ndata: {"message_id":"m1","steps":["router","tool_executor","generator"],"session_id":"s1"}\n\n',
    ])

    const { messages, streaming, send } = useChatStream()
    await send('这学期上什么课')

    const [user, assistant] = messages.value.slice(-2)
    expect(user.role).toBe('user')
    expect(assistant.text).toBe('已为你找到课表页')
    expect(assistant.toolCall).toEqual({ name: 'resolve_page', ok: true, latencyMs: 23 })
    expect(assistant.navCard?.path).toBe('/academic/schedule')
    expect(assistant.error).toBeNull()
    expect(streaming.value).toBe(false)
  })

  it('error 事件写入气泡错误态', async () => {
    stubStream([
      'event: error\ndata: {"code":"recursion_limit","message":"图超出步数上限"}\n\n',
    ])

    const { messages, send } = useChatStream()
    await send('随便说点什么')

    const assistant = messages.value[messages.value.length - 1]
    expect(assistant.error).toBe('recursion_limit: 图超出步数上限')
  })
})
