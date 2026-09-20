<script setup lang="ts">
/**
 * 节次导轨：整站的签名件。左轨是 1–8 节课的时间脊线，右侧按天铺课程块。
 * 首页只传今天一列（变成"今日安排"），课表页传五列（周课表），同一装置两种读数。
 */
import { computed } from 'vue'
import { courses, md, nowPeriod, periods, weekdays, type CourseEntry } from '../data/seed'

const props = withDefaults(defineProps<{
  days: number[]
  detailed?: boolean
  items?: CourseEntry[]
}>(), { detailed: false, items: () => courses })

const shown = computed(() => props.items)

const dayNow = computed(() => new Date().getDay())

const live = computed(() => nowPeriod())
const activeIndex = computed(() => live.value.index)

/** 本周各天的日期读数，让"周一"落到具体的某一天 */
function dateOf(day: number): string {
  const now = new Date()
  const js = now.getDay()
  const mondayOffset = js === 0 ? -6 : 1 - js
  const target = new Date(now.getTime() + (mondayOffset + day - 1) * 86_400_000)
  return md(target)
}

function at(day: number, period: number): CourseEntry | undefined {
  return shown.value.find((c) => c.day === day && c.periods[0] === period)
}

function spans(day: number, period: number): boolean {
  return shown.value.some((c) => c.day === day && c.periods.includes(period) && c.periods[0] !== period)
}

function isNow(c: CourseEntry): boolean {
  // 必须同时命中"今天这一列"，否则周课表会把别天的同节次课也点亮
  return activeIndex.value !== null && c.day === dayNow.value && c.periods.includes(activeIndex.value)
}
</script>

<template>
  <div class="scroller">
    <div class="grid" :style="{ '--cols': days.length }">
      <div class="corner"><span class="corner-label">节次</span></div>

      <div
        v-for="d in days"
        :key="'h' + d"
        class="dayhead"
        :class="{ 'is-today': d === dayNow && days.length > 1 }"
        :style="{ gridRow: 1, gridColumn: days.indexOf(d) + 2 }"
      >
        <span class="dw">{{ weekdays[d - 1] }}</span>
        <span class="dt num">{{ dateOf(d) }}</span>
      </div>

      <template v-for="p in periods" :key="'r' + p.index">
        <div class="rail" :class="{ 'is-now': p.index === activeIndex }" :style="{ gridRow: p.index + 1, gridColumn: 1 }">
          <span class="idx num">{{ p.index }}</span>
          <span class="time code">{{ p.start }}–{{ p.end }}</span>
          <span v-if="p.index === activeIndex" class="tick">现在</span>
        </div>

        <div
          v-for="d in days"
          :key="'c' + p.index + '-' + d"
          class="cell"
          :class="{ 'is-blank': !at(d, p.index) && !spans(d, p.index) }"
          :style="{ gridRow: p.index + 1, gridColumn: days.indexOf(d) + 2 }"
        />
      </template>

      <article
        v-for="c in shown.filter((x) => days.includes(x.day))"
        :key="c.code + c.day"
        class="course"
        :class="{ 'is-now': isNow(c), 'is-slim': !detailed }"
        :style="{
          gridRow: `${c.periods[0] + 1} / span ${c.periods.length}`,
          gridColumn: days.indexOf(c.day) + 2,
        }"
      >
        <div class="course-head">
          <h3>{{ c.name }}</h3>
          <span v-if="isNow(c)" class="live-dot" aria-label="正在上课" />
        </div>
        <p class="room">{{ c.room }}</p>
        <dl v-if="detailed" class="detail">
          <div><dt>教师</dt><dd>{{ c.teacher }}</dd></div>
          <div><dt>学分</dt><dd class="num">{{ c.credits }}</dd></div>
          <div><dt>周次</dt><dd class="num">{{ c.weeks }} 周</dd></div>
          <div><dt>性质</dt><dd>{{ c.kind }}</dd></div>
        </dl>
        <p v-else class="sub">{{ c.teacher }} · {{ c.credits }} 学分</p>
      </article>
    </div>
  </div>
</template>

<style scoped>
.scroller {
  overflow-x: auto;
  padding-bottom: 2px;
}

.grid {
  display: grid;
  grid-template-columns: 86px repeat(var(--cols), minmax(0, 1fr));
  grid-template-rows: 42px repeat(8, minmax(56px, auto));
  min-width: calc(var(--cols) * 148px + 86px);
  position: relative;
}

.corner {
  grid-row: 1;
  grid-column: 1;
  display: flex;
  align-items: flex-end;
  padding: 0 10px 6px 0;
  border-bottom: 1px solid var(--rule-2);
}

.corner-label {
  font-family: var(--display);
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.dayhead {
  grid-row: 1;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 0 10px 6px;
  border-bottom: 1px solid var(--rule-2);
}

.dayhead .dw {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-2);
}

.dayhead .dt {
  font-size: 12px;
  color: var(--faint);
}

.dayhead.is-today .dw {
  color: var(--seal);
}

.dayhead.is-today .dt {
  color: var(--seal);
}

/* 导轨列 */
.rail {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  padding: 7px 10px 0 0;
  border-right: 1px solid var(--rule-2);
  position: relative;
}

.rail .idx {
  font-size: 15px;
  font-weight: 600;
  line-height: 1;
}

.rail .time {
  color: var(--faint);
  font-size: 11px;
}

.rail.is-now .idx {
  color: var(--seal);
}

.rail.is-now::after {
  content: '';
  position: absolute;
  right: -1px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--seal);
}

.tick {
  font-family: var(--display);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: #fff;
  background: var(--seal);
  border-radius: 2px;
  padding: 1px 5px;
  margin-top: 3px;
}

.cell {
  border-bottom: 1px dashed var(--rule);
}

.cell.is-blank {
  border-bottom-style: solid;
}

.course {
  position: relative;
  z-index: 1;
  margin: 4px;
  padding: 8px 10px;
  background: var(--card);
  border: 1px solid var(--rule);
  border-left: 3px solid var(--ink);
  border-radius: var(--r-sm);
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: box-shadow 0.16s ease, transform 0.16s ease;
}

.course:hover {
  box-shadow: var(--shadow);
}

.course h3 {
  font-size: 13.5px;
  line-height: 1.3;
}

.course-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
}

.room {
  font-size: 12px;
  color: var(--text);
}

.sub {
  font-size: 11.5px;
  color: var(--faint);
}

.is-slim {
  padding: 6px 8px;
}

/* 正在上的那一节：整页唯一一处朱红填充 */
.course.is-now {
  border-left-color: var(--seal);
  background: var(--seal-veil);
}

.live-dot {
  width: 7px;
  height: 7px;
  flex: none;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--seal);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.8); }
}

.detail {
  margin: 6px 0 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px 10px;
}

.detail div {
  display: flex;
  align-items: baseline;
  gap: 5px;
}

.detail dt {
  font-size: 11px;
  color: var(--faint);
}

.detail dd {
  margin: 0;
  font-size: 12px;
  color: var(--ink);
}

@media (max-width: 720px) {
  .detail {
    grid-template-columns: 1fr;
  }
}
</style>
