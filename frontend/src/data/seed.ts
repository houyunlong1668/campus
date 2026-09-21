import type { CourseEntry, GradeRow } from '../types'

/** 展示常量与纯函数。课表、成绩、借阅等业务数据一律来自 /api/*（spec 8.3）。 */

/** 教务系统式的月日读数：09-28 */
export function md(d: Date): string {
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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

/** 学期抬头与周次：仿真环境无教务日历，作为展示常量固定（S3 之后再接真实校历） */
export const termMeta = {
  semester: '2026–2027 学年 第一学期',
  week: 6,
  totalWeeks: 19,
  creditsRequired: 165,
}

/** 图书馆馆情常量：座位与罚款额度不是学生个人数据 */
export const libraryMeta = {
  quota: 10,
  seatsOpen: 47,
  seatsTotal: 220,
  fine: '6.00 元',
}

/** 5.0 分制：绩点 = (分数 − 50) / 10，90 分以上封顶 5.0 */
export function points(score: number): number {
  if (score < 60) return 0
  return Math.round(Math.min((score - 50) / 10, 5) * 10) / 10
}

export function gpaOf(grades: GradeRow[]): number {
  if (!grades.length) return 0
  const total = grades.reduce((s, g) => s + g.credits, 0)
  const weighted = grades.reduce((s, g) => s + points(g.score) * g.credits, 0)
  return Math.round((weighted / total) * 100) / 100
}

export function creditsDoneOf(grades: GradeRow[]): number {
  return Math.round(grades.reduce((s, g) => s + g.credits, 0) * 10) / 10
}

/** 把当前时刻映射到节次：课间返回 null，但给出下一节的定位 */
export function nowPeriod(courses: CourseEntry[]): {
  index: number | null
  next: { course: CourseEntry; period: Period } | null
} {
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

export function todayCourses(courses: CourseEntry[]): CourseEntry[] {
  const day = new Date().getDay()
  return courses
    .filter((c) => c.day === day)
    .sort((a, b) => a.periods[0] - b.periods[0])
}

/** 未来 7 天内第一节还没上的课，用于"此刻无课"时给出真正的下一步 */
export function nextUp(courses: CourseEntry[]): { course: CourseEntry; period: Period; dayOffset: number } | null {
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
