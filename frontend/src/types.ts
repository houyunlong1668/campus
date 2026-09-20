export interface ChatRequest {
  message: string
}

export interface StudentInfo {
  student_id: string
  name: string
  major: string
  class_name: string
  college: string
}

export interface ToolCallEvent {
  name: string
  args: Record<string, unknown>
  ok: boolean
  error: string | null
  latency_ms: number
}

export interface TokenEvent { text: string }
export interface NavCardEvent { path: string; title: string; reason: string }
export interface DoneEvent { message_id: string; steps: string[]; session_id: string }
export interface ErrorEvent { code: string; message: string }

export interface NavCard {
  path: string
  title: string
  reason: string
}
