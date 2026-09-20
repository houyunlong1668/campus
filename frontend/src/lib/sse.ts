export interface SSEFrame {
  event: string
  data: string
}

export function createSSEParser() {
  const decoder = new TextDecoder()
  let buffer = ''
  return {
    feed(chunk: Uint8Array): SSEFrame[] {
      // 合规发射器可能发 CRLF，统一成 LF 再按空行切帧
      buffer += decoder.decode(chunk, { stream: true }).replace(/\r\n/g, '\n')
      const frames: SSEFrame[] = []
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        let event = 'message'
        const dataLines: string[] = []
        for (const line of raw.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim() || 'message'
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
        }
        if (dataLines.length) frames.push({ event, data: dataLines.join('\n') })
      }
      return frames
    },
  }
}
