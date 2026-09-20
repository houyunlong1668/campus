/** 仿真教务数据。日期一律从当前时钟推导，演示时永远不会"过期"。 */

const DAY = 86_400_000

function fromToday(offsetDays: number): Date {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return new Date(d.getTime() + offsetDays * DAY)
}

/** 教务系统式的日期串：2026-09-28 周一 09:00 */
export function stamp(d: Date, time = '09:00'): string {
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd} ${week} ${time}`
}

export function md(d: Date): string {
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export const student = {
  name: '周晓楠',
  id: '20230001',
  major: '计算机科学与技术',
  className: '计科 2301',
  college: '信息科学与工程学院',
  semester: '2026–2027 学年 第一学期',
  week: 6,
  totalWeeks: 19,
  creditsRequired: 165,
}

export interface Period {
  index: number
  start: string
  end: string
  label: string
}

/** 真实高校作息：上下午各两连节，傍晚两节体育/选修 */
export const periods: Period[] = [
  { index: 1, start: '08:00', end: '08:50', label: '第 1 节' },
  { index: 2, start: '08:50', end: '09:40', label: '第 2 节' },
  { index: 3, start: '10:00', end: '10:50', label: '第 3 节' },
  { index: 4, start: '10:50', end: '11:40', label: '第 4 节' },
  { index: 5, start: '14:00', end: '14:50', label: '第 5 节' },
  { index: 6, start: '14:50', end: '15:40', label: '第 6 节' },
  { index: 7, start: '16:20', end: '17:10', label: '第 7 节' },
  { index: 8, start: '17:10', end: '18:00', label: '第 8 节' },
]

export const weekdays = ['周一', '周二', '周三', '周四', '周五']

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

export const courses: CourseEntry[] = [
  { name: '高等数学（下）', code: 'MATH2041', teacher: '王建国', room: '主楼 A302', day: 1, periods: [1, 2], credits: 5, weeks: '1-16', kind: '必修', domain: 'math' },
  { name: '数据结构', code: 'CS2052', teacher: '李慧', room: '实验楼 B101', day: 1, periods: [3, 4], credits: 4, weeks: '1-16', kind: '必修', domain: 'cs' },
  { name: '体育（篮球）', code: 'PE2061', teacher: '陈毅', room: '风雨球馆 2 号场', day: 1, periods: [7, 8], credits: 1, weeks: '2-17', kind: '必修', domain: 'pe' },
  { name: '大学英语（四）', code: 'FL2034', teacher: 'Chen Min', room: '外语楼 C203', day: 2, periods: [1, 2], credits: 2, weeks: '1-14', kind: '必修', domain: 'lang' },
  { name: '离散数学', code: 'MATH2032', teacher: '孙立', room: '主楼 A205', day: 2, periods: [5, 6], credits: 3.5, weeks: '1-16', kind: '必修', domain: 'math' },
  { name: '计算机网络', code: 'CS3011', teacher: '赵东', room: '主楼 A415', day: 3, periods: [3, 4], credits: 3.5, weeks: '3-18', kind: '必修', domain: 'cs' },
  { name: '算法设计与分析', code: 'CS3021', teacher: '周涛', room: '实验楼 B207', day: 3, periods: [5, 6], credits: 3, weeks: '3-18', kind: '必修', domain: 'cs' },
  { name: '操作系统', code: 'CS3031', teacher: '吴敏', room: '主楼 A302', day: 4, periods: [1, 2], credits: 4, weeks: '4-19', kind: '必修', domain: 'cs' },
  { name: '概率论与数理统计', code: 'MATH2042', teacher: '何秀', room: '主楼 A205', day: 4, periods: [3, 4], credits: 3.5, weeks: '4-19', kind: '必修', domain: 'math' },
  { name: '人工智能导论', code: 'CS3099', teacher: '林一', room: '实验楼 B305', day: 4, periods: [7, 8], credits: 2, weeks: '5-16', kind: '选修', domain: 'cs' },
  { name: '中国近现代史纲要', code: 'HS2012', teacher: '徐平', room: '文渊楼报告厅', day: 5, periods: [1, 2], credits: 3, weeks: '1-14', kind: '必修', domain: 'hum' },
  { name: '数据库系统实验', code: 'CS2062', teacher: '郑好', room: '实验楼 B108', day: 5, periods: [5, 6], credits: 1.5, weeks: '6-18', kind: '实践', domain: 'lab' },
]

export interface GradeRow {
  name: string
  code: string
  credits: number
  score: number
  term: string
}

/** 已修课程成绩；绩点按 (分数 − 50) / 10 折算，60 分以下计 0 */
export const grades: GradeRow[] = [
  { name: '高等数学（上）', code: 'MATH2031', credits: 5, score: 91, term: '2025 秋' },
  { name: 'C 语言程序设计', code: 'CS1011', credits: 4, score: 95, term: '2025 秋' },
  { name: '线性代数', code: 'MATH1021', credits: 3, score: 84, term: '2025 秋' },
  { name: '大学物理（上）', code: 'PHY1031', credits: 4, score: 56, term: '2025 秋' },
  { name: '计算机导论', code: 'CS1001', credits: 2, score: 82, term: '2025 秋' },
  { name: '思想道德与法治', code: 'HS1011', credits: 3, score: 90, term: '2025 秋' },
  { name: '体育（一）', code: 'PE1011', credits: 1, score: 0, term: '2025 秋' },
  { name: '大学英语（三）', code: 'FL1033', credits: 2, score: 89, term: '2025 秋' },
  { name: '数字逻辑', code: 'CS1041', credits: 3, score: 78, term: '2026 春' },
  { name: '大学物理（下）', code: 'PHY1032', credits: 3.5, score: 83, term: '2026 春' },
  { name: '面向对象程序设计', code: 'CS2042', credits: 3, score: 92, term: '2026 春' },
  { name: '体育（二）', code: 'PE1012', credits: 1, score: 88, term: '2026 春' },
  { name: '数据结构（暑期补习）', code: 'CS2052', credits: 4, score: 87, term: '2026 春' },
]

/** 5.0 分制：绩点 = (分数 − 50) / 10，90 分以上封顶 5.0 */

export function points(score: number): number {
  if (score < 60) return 0
  return Math.round(Math.min((score - 50) / 10, 5) * 10) / 10
}

export const gpa = (() => {
  const total = grades.reduce((s, g) => s + g.credits, 0)
  const weighted = grades.reduce((s, g) => s + points(g.score) * g.credits, 0)
  return Math.round((weighted / total) * 100) / 100
})()

/** 已修学分只有一个来源：成绩表本身 */
export const creditsDone = Math.round(grades.reduce((s, g) => s + g.credits, 0) * 10) / 10

export const failedCount = grades.filter((g) => g.score < 60).length

export interface MakeupItem {
  course: string
  code: string
  type: '补考' | '重修'
  reason: string
  when: string
  place: string
  status: '已报名' | '待缴费' | '报名中'
  seats?: string
}

export const makeup: MakeupItem[] = [
  {
    course: '大学物理（上）', code: 'PHY1031', type: '补考', reason: '期末 56 分，未达 60 分线',
    when: stamp(fromToday(8), '09:00'), place: '主楼 A102', status: '已报名',
  },
  {
    course: '体育（一）', code: 'PE1011', type: '重修', reason: '缺考，成绩记为 0 分',
    when: stamp(fromToday(22), '14:00'), place: '风雨球馆 1 号场', status: '待缴费',
  },
  {
    course: '概率论与数理统计', code: 'MATH2042', type: '重修', reason: '上学期未选，本学期补选',
    when: `报名截止 ${md(fromToday(4))} 17:00`, place: '线上教务系统', status: '报名中', seats: '剩 23 / 120',
  },
]

export interface LoanItem {
  title: string
  callNo: string
  due: string
  /** 距应还日剩余天数，负数为已逾期 */
  daysLeft: number
  place: string
}

export const loans: LoanItem[] = [
  { title: '算法导论（第三版）上册', callNo: 'TP301.6 / C24', due: stamp(fromToday(2), '20:00'), daysLeft: 2, place: '三楼自然科学借阅区' },
  { title: '深入理解计算机系统（第 3 版）', callNo: 'TP368.1 / Z33', due: stamp(fromToday(-3), '20:00'), daysLeft: -3, place: '三楼自然科学借阅区' },
  { title: '数据库系统概念（第 7 版）', callNo: 'TP311.13 / A25', due: stamp(fromToday(11), '20:00'), daysLeft: 11, place: '三楼自然科学借阅区' },
  { title: '人类简史：从动物到上帝', callNo: 'K02 / H44', due: stamp(fromToday(6), '20:00'), daysLeft: 6, place: '五楼人文社科借阅区' },
]

export const libraryStats = {
  borrowed: loans.length,
  overdue: loans.filter((l) => l.daysLeft < 0).length,
  quota: 10,
  seatsOpen: 47,
  seatsTotal: 220,
  fine: '6.00 元',
}

/** 把当前时刻映射到节次：课间返回 null，但给出下一节的定位 */
export function nowPeriod(): { index: number | null; next: { course: CourseEntry; period: Period } | null } {
  const now = new Date()
  const day = now.getDay()
  const mins = now.getHours() * 60 + now.getMinutes()
  const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))

  let index: number | null = null
  for (const p of periods) {
    if (mins >= toMin(p.start) && mins < toMin(p.end)) index = p.index
  }

  const today = courses.filter((c) => c.day === day)
  let next: { course: CourseEntry; period: Period } | null = null
  for (const c of today) {
    const first = periods.find((p) => p.index === c.periods[0])
    if (first && toMin(first.start) > mins) {
      if (!next || toMin(first.start) < toMin(periods.find((p) => p.index === next!.course.periods[0])!.start)) {
        next = { course: c, period: first }
      }
    }
  }
  return { index, next }
}

/** 未来 7 天内第一节还没上的课，用于"此刻无课"时给出真正的下一步 */
export function nextUp(): { course: CourseEntry; period: Period; dayOffset: number } | null {
  const now = new Date()
  const mins = now.getHours() * 60 + now.getMinutes()
  const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))
  const today = now.getDay()

  for (let offset = 0; offset < 7; offset++) {
    const day = offset === 0 ? today : ((today - 1 + offset) % 7) + 1
    if (day > 5) continue
    const list = courses
      .filter((c) => c.day === day)
      .map((c) => ({ c, p: periods.find((x) => x.index === c.periods[0])! }))
      .filter((x) => offset > 0 || toMin(x.p.start) > mins)
      .sort((a, b) => a.p.index - b.p.index)
    if (list.length) return { course: list[0].c, period: list[0].p, dayOffset: offset }
  }
  return null
}

export function todayCourses(): CourseEntry[] {
  const day = new Date().getDay()
  return courses
    .filter((c) => c.day === day)
    .sort((a, b) => a.periods[0] - b.periods[0])
}
