import { describe, expect, it } from 'vitest'
import { createSSEParser } from '../src/lib/sse'

const enc = (s: string) => new TextEncoder().encode(s)

describe('createSSEParser', () => {
  it('解析单个完整帧', () => {
    const p = createSSEParser()
    expect(p.feed(enc('event: token\ndata: {"text":"你好"}\n\n'))).toEqual([
      { event: 'token', data: '{"text":"你好"}' },
    ])
  })

  it('跨 chunk 的半截帧先不产出', () => {
    const p = createSSEParser()
    expect(p.feed(enc('event: token\nda'))).toEqual([])
    expect(p.feed(enc('ta: {"text":"x"}\n\n'))).toEqual([
      { event: 'token', data: '{"text":"x"}' },
    ])
  })

  it('多帧粘连一次产出', () => {
    const p = createSSEParser()
    const frames = p.feed(enc(
      'event: token\ndata: {"text":"a"}\n\nevent: nav_card\ndata: {"path":"/x"}\n\n',
    ))
    expect(frames.map((f) => f.event)).toEqual(['token', 'nav_card'])
  })

  it('CRLF 帧分隔同样识别', () => {
    const p = createSSEParser()
    expect(p.feed(enc('event: token\r\ndata: {"text":"a"}\r\n\r\n'))).toEqual([
      { event: 'token', data: '{"text":"a"}' },
    ])
  })

  it('UTF-8 多字节字符被 chunk 切断后正确重组', () => {
    const p = createSSEParser()
    const bytes = enc('data: {"text":"课表"}\n\n')
    const cut = bytes.slice(0, 12) // 恰好在"课"的中间切开
    expect(p.feed(cut)).toEqual([])
    expect(p.feed(bytes.slice(12))).toEqual([
      { event: 'message', data: '{"text":"课表"}' },
    ])
  })
})
