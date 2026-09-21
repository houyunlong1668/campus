<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import TimetableGrid from '../components/TimetableGrid.vue'
import { useAssistant } from '../composables/useAssistant'
import { useResource } from '../composables/useResource'
import {
  creditsDoneOf, gpaOf, libraryMeta, nextUp, nowPeriod, periods, termMeta, todayCourses,
} from '../data/seed'
import type { CourseEntry, GradeRow, LoanItem, MakeupItem } from '../types'

const { ask } = useAssistant()

const scheduleR = useResource<{ courses: CourseEntry[] }>('/api/schedule')
const gradesR = useResource<{ grades: GradeRow[] }>('/api/grades')
const makeupR = useResource<{ items: MakeupItem[] }>('/api/makeup')
const loansR = useResource<{ items: LoanItem[] }>('/api/loans')

function reloadAll() {
  void Promise.all([scheduleR.reload(), gradesR.reload(), makeupR.reload(), loansR.reload()])
}
onMounted(reloadAll)

const courses = computed(() => scheduleR.data.value?.courses ?? [])
const grades = computed(() => gradesR.data.value?.grades ?? [])
const makeup = computed(() => makeupR.data.value?.items ?? [])
const loans = computed(() => loansR.data.value?.items ?? [])

const loading = computed(() =>
  scheduleR.loading.value || gradesR.loading.value || makeupR.loading.value || loansR.loading.value)
const error = computed(() =>
  scheduleR.error.value || gradesR.error.value || makeupR.error.value || loansR.error.value)

const dayNames = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const now = new Date()
const jsDay = now.getDay()
const live = computed(() => nowPeriod(courses.value))
const agenda = computed(() => todayCourses(courses.value))

const gpa = computed(() => gpaOf(grades.value))
const creditsDone = computed(() => creditsDoneOf(grades.value))

/** 首页抬头只说一件事：此刻该干什么 */
const status = computed(() => {
  const idx = live.value.index
  if (idx !== null) {
    const c = agenda.value.find((x) => x.periods.includes(idx))
    const p = periods.find((x) => x.index === idx)!
    return c
      ? { lead: `正在上第 ${idx} 节`, main: c.name, tail: `${p.start}–${p.end} · ${c.room}` }
      : { lead: `第 ${idx} 节`, main: '本节无课', tail: `${p.start}–${p.end} · 可用于自习` }
  }
  if (live.value.next) {
    const { course, period } = live.value.next
    return { lead: `下一节 ${period.start}`, main: course.name, tail: `${course.room} · ${course.teacher}` }
  }
  if (agenda.value.length) {
    return { lead: '今日课程已全部结束', main: `${agenda.value.length} 节课已完成`, tail: nextLine() }
  }
  return { lead: `${dayNames[jsDay]}没有排课`, main: '今天不上课', tail: nextLine() }
})

/** 此刻没课时，最有用的信息是"下一次什么时候上课" */
function nextLine(): string {
  const n = nextUp(courses.value)
  if (!n) return '未来一周没有排课'
  const when = n.dayOffset === 0 ? '今天' : n.dayOffset === 1 ? '明天' : dayNames[(jsDay + n.dayOffset) % 7]
  return `下次课 ${when} ${n.period.start} · ${n.course.name}`
}

const weekPct = computed(() => Math.round((termMeta.week / termMeta.totalWeeks) * 100))
const creditPct = computed(() => Math.round((creditsDone.value / termMeta.creditsRequired) * 100))
const weeklySessions = computed(() => courses.value.reduce((s, c) => s + c.periods.length, 0))

const overdue = computed(() => loans.value.filter((l) => l.daysLeft < 0))
const dueSoon = computed(() => loans.value.filter((l) => l.daysLeft >= 0 && l.daysLeft <= 3))

const reminders = computed(() => {
  const items: { to: string; tag: string; title: string; meta: string; urgent: boolean }[] = []
  const m = makeup.value[0]
  if (m) {
    items.push({ to: '/academic/makeup', tag: m.type, title: m.course,
                 meta: `${m.when} · ${m.place}`, urgent: false })
  }
  if (overdue.value.length) {
    items.push({
      to: '/library', tag: '逾期', title: `${overdue.value.length} 本图书已逾期`,
      meta: `应还 ${overdue.value[0].due.slice(0, 10)} · 罚款 ${libraryMeta.fine}`, urgent: true,
    })
  }
  if (dueSoon.value.length) {
    items.push({
      to: '/library', tag: '应还', title: `${dueSoon.value.length} 本图书 3 日内应还`,
      meta: `最近一本 ${dueSoon.value[0].title}`, urgent: false,
    })
  }
  items.push({ to: '/academic/grades', tag: '成绩', title: `${gpa.value} 平均绩点`,
               meta: `${makeup.value.length} 门课程需补考或重修`, urgent: false })
  return items
})

const prompts = [
  '这学期上什么课',
  '查一下我的成绩',
  '补考什么时候',
  '图书馆还有哪些没还',
]
</script>

<template>
  <div class="home">
    <div v-if="loading" class="state-block" role="status">
      <p class="state-title">正在读取教务数据…</p>
      <div class="state-skeleton"><span /><span /><span /></div>
    </div>
    <div v-else-if="error" class="state-block" role="alert">
      <p class="state-title">{{ error }}</p>
      <button type="button" class="state-retry" @click="reloadAll">重试</button>
    </div>
    <template v-else>
    <section class="hero">
      <div class="hero-main">
        <p class="eyebrow">{{ now.getFullYear() }}-{{ String(now.getMonth() + 1).padStart(2, '0') }}-{{ String(now.getDate()).padStart(2, '0') }} {{ dayNames[jsDay] }} · 第 {{ termMeta.week }} 周</p>
        <h1>{{ status.lead }}</h1>
        <p class="hero-course">{{ status.main }}</p>
        <p class="hero-tail">{{ status.tail }}</p>
      </div>

      <div class="hero-side">
        <div class="gauge">
          <div class="gauge-row">
            <span class="gauge-label">学期进度</span>
            <span class="gauge-val num">{{ termMeta.week }}/{{ termMeta.totalWeeks }} 周</span>
          </div>
          <div class="bar"><span :style="{ width: weekPct + '%' }" /></div>
        </div>
        <div class="gauge">
          <div class="gauge-row">
            <span class="gauge-label">已修学分</span>
            <span class="gauge-val num">{{ creditsDone }}/{{ termMeta.creditsRequired }}</span>
          </div>
          <div class="bar"><span :style="{ width: creditPct + '%' }" /></div>
        </div>
        <p class="gauge-note">本周 <span class="num">{{ weeklySessions }}</span> 节 · 今日 <span class="num">{{ agenda.length }}</span> 节</p>
      </div>
    </section>

    <section class="block">
      <div class="block-head">
        <h2>今日安排</h2>
        <RouterLink to="/academic/schedule" class="link">看整周课表 →</RouterLink>
      </div>
      <TimetableGrid v-if="agenda.length" :days="[jsDay]" :items="agenda" detailed class="today" />
      <div v-else class="empty">
        <p class="empty-title">今天没有课</p>
        <p class="empty-hint">{{ nextLine() }}。要看看整周安排，还是问助手别的事？</p>
      </div>
    </section>

    <section class="block">
      <div class="block-head"><h2>待办与提醒</h2></div>
      <p v-if="!reminders.length" class="empty-hint">暂时没有待办。</p>
      <ul class="reminders">
        <li v-for="r in reminders" :key="r.title">
          <RouterLink :to="r.to" class="reminder" :class="{ 'is-urgent': r.urgent }">
            <span class="tag">{{ r.tag }}</span>
            <span class="reminder-body">
              <span class="reminder-title">{{ r.title }}</span>
              <span class="reminder-meta">{{ r.meta }}</span>
            </span>
            <span class="go" aria-hidden="true">→</span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <section class="block">
      <div class="ask">
        <div class="ask-copy">
          <h2>不确定在哪一页？直接问</h2>
          <p>右下角助手会调用教务页面清单，把问题定位到具体页面并跳转。</p>
        </div>
        <div class="chips">
          <button v-for="p in prompts" :key="p" type="button" class="chip" @click="ask(p)">{{ p }}</button>
        </div>
      </div>
    </section>
    </template>
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 34px;
}

.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 32px;
  align-items: start;
  padding-bottom: 26px;
  border-bottom: 1px solid var(--rule);
}

.hero-main h1 {
  margin: 10px 0 6px;
  font-size: 34px;
}

.hero-course {
  font-family: var(--display);
  font-size: 21px;
  font-weight: 600;
  color: var(--ink-2);
  letter-spacing: 0.01em;
}

.hero-tail {
  margin-top: 4px;
  font-size: 13.5px;
  color: var(--faint);
}

.hero-side {
  border-left: 1px solid var(--rule);
  padding-left: 24px;
}

.gauge + .gauge {
  margin-top: 16px;
}

.gauge-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
}

.gauge-label {
  font-size: 12.5px;
  color: var(--faint);
}

.gauge-val {
  font-size: 14px;
  font-weight: 600;
}

.bar {
  height: 3px;
  margin-top: 6px;
  background: var(--rule);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--ink);
  transition: width 0.5s ease;
}

.gauge-note {
  margin-top: 16px;
  font-size: 12.5px;
  color: var(--faint);
}

.block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.link {
  font-size: 13px;
  color: var(--ink-2);
  border-bottom: 1px solid var(--rule-2);
  padding-bottom: 1px;
}

.link:hover {
  color: var(--seal);
  border-bottom-color: var(--seal);
}

.today {
  border: 1px solid var(--rule);
  background: var(--card);
  border-radius: var(--r-md);
  padding: 6px 8px 10px;
  max-width: 780px;
}

.today :deep(.grid) {
  min-width: 0;
  grid-template-columns: 86px minmax(0, 1fr);
}

.empty {
  border: 1px dashed var(--rule-2);
  border-radius: var(--r-md);
  padding: 34px 20px;
  text-align: center;
  background: var(--card);
}

.empty-title {
  font-family: var(--display);
  font-size: 17px;
  font-weight: 600;
  color: var(--ink);
}

.empty-hint {
  margin-top: 6px;
  font-size: 13px;
  color: var(--faint);
}

.reminders {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.reminder {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 14px;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.reminder:hover {
  border-color: var(--ink-2);
  box-shadow: var(--shadow);
}

.tag {
  flex: none;
  font-family: var(--display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--ink-2);
  border: 1px solid var(--rule-2);
  border-radius: 2px;
  padding: 2px 6px;
}

.reminder.is-urgent .tag {
  color: #fff;
  background: var(--seal);
  border-color: var(--seal);
}

.reminder-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.reminder-title {
  font-size: 14px;
  color: var(--ink);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reminder-meta {
  font-size: 12px;
  color: var(--faint);
}

.go {
  flex: none;
  color: var(--faint);
  font-size: 14px;
  transition: transform 0.16s ease, color 0.16s ease;
}

.reminder:hover .go {
  color: var(--seal);
  transform: translateX(2px);
}

.ask {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  background: var(--ink);
  color: #e7ebf2;
  border-radius: var(--r-md);
  padding: 20px 24px;
}

.ask h2 {
  color: #fff;
}

.ask-copy p {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(231, 235, 242, 0.7);
  max-width: 44ch;
}

.chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chip {
  font: inherit;
  font-size: 13px;
  color: #e7ebf2;
  background: transparent;
  border: 1px solid rgba(231, 235, 242, 0.3);
  border-radius: 100px;
  padding: 6px 14px;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease, border-color 0.16s ease;
}

.chip:hover {
  background: #fff;
  color: var(--ink);
  border-color: #fff;
}

@media (max-width: 860px) {
  .hero {
    grid-template-columns: minmax(0, 1fr);
  }

  .hero-side {
    border-left: none;
    border-top: 1px solid var(--rule);
    padding-left: 0;
    padding-top: 18px;
  }

  .reminders {
    grid-template-columns: minmax(0, 1fr);
  }
}

.state-block {
  padding: 34px 20px;
  border: 1px dashed var(--rule-2);
  border-radius: var(--r-md);
  background: var(--card);
  text-align: center;
}

.state-title {
  font-size: 13.5px;
  color: var(--faint);
}

.state-skeleton {
  margin-top: 16px;
  display: grid;
  gap: 8px;
}

.state-skeleton span {
  height: 12px;
  border-radius: 2px;
  background: var(--rule);
}

.state-skeleton span:nth-child(1) { width: 62%; }
.state-skeleton span:nth-child(2) { width: 84%; }
.state-skeleton span:nth-child(3) { width: 45%; }

.state-retry {
  font: inherit;
  font-size: 13px;
  margin-top: 14px;
  padding: 7px 16px;
  color: #fff;
  background: var(--ink);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.state-retry:hover {
  background: var(--seal);
  border-color: var(--seal);
}
</style>
