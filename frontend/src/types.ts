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
export interface DoneEvent { message_id: string; steps: string[]; conversation_id: number | null }
export interface ErrorEvent { code: string; message: string }

export interface ClarifyOption { label: string }
export interface ClarifyEvent {
  question: string
  options: ClarifyOption[]
}
export interface SqlResultEvent {
  sql: string
  columns: string[]
  rows: (string | number | null)[][]
  row_count: number
  truncated: boolean
}

export interface NavCard {
  path: string
  title: string
  reason: string
}

/** 学科域：课表配色的依据，颜色在此承载真实信息而非装饰 */
export type Domain = 'math' | 'cs' | 'lang' | 'pe' | 'hum' | 'lab'

export const DOMAIN_LABELS: Record<Domain, string> = {
  math: '数学',
  cs: '计算机',
  lang: '外语',
  pe: '体育',
  hum: '人文',
  lab: '实践',
}

/** 以下四个接口逐字对应 Task 5 的 /api/* 响应字段 */
export interface GradeRow {
  name: string
  code: string
  credits: number
  score: number
  term: string
}

export interface CourseEntry {
  name: string
  code: string
  teacher: string
  room: string
  /** 1=周一 … 5=周五 */
  day: number
  /** 节次序号，连堂写成 [3, 4] */
  periods: number[]
  credits: number
  weeks: string
  kind: '必修' | '选修' | '实践'
  domain: Domain
}

export interface MakeupItem {
  course: string
  code: string
  type: '补考' | '重修'
  reason: string
  when: string
  place: string
  status: '已报名' | '待缴费' | '报名中'
  seats: string | null
}

export interface LoanItem {
  title: string
  callNo: string
  due: string
  /** 距应还日剩余天数，负数为已逾期 */
  daysLeft: number
  place: string
}
