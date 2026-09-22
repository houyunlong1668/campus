<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import TimetableGrid from '../components/TimetableGrid.vue'
import { useResource } from '../composables/useResource'
import { periods, termMeta, weekdays } from '../data/seed'
import { DOMAIN_LABELS, type CourseEntry, type Domain } from '../types'

const { data, loading, error, reload } = useResource<{ courses: CourseEntry[] }>('/api/schedule')
onMounted(reload)

const courses = computed(() => data.value?.courses ?? [])
const activeWeek = ref(termMeta.week)
watch(courses, (v) => { if (v.length && activeWeek.value > termMeta.totalWeeks) activeWeek.value = termMeta.week })
const weeks = Array.from({ length: termMeta.totalWeeks }, (_, i) => i + 1)

function inWeek(range: string, week: number): boolean {
  const [start, end] = range.split('-').map(Number)
  return week >= start && week <= (end || start)
}

const shown = computed(() => courses.value.filter((c) => inWeek(c.weeks, activeWeek.value)))
const visibleDomains = computed(() =>
  (Object.keys(DOMAIN_LABELS) as Domain[]).filter((d) => shown.value.some((c) => c.domain === d)),
)
const countOf = (d: Domain) => shown.value.filter((c) => c.domain === d).length
</script>

<template>
  <div class="page-body">
    <div v-if="loading" class="state-block" role="status">
      <p class="state-title">正在读取教务数据…</p>
      <div class="state-skeleton"><span /><span /><span /></div>
    </div>
    <div v-else-if="error" class="state-block" role="alert">
      <p class="state-title">{{ error }}</p>
      <button type="button" class="state-retry" @click="reload">重试</button>
    </div>
    <template v-else>
    <header class="head">
      <div>
        <p class="eyebrow">{{ termMeta.semester }}</p>
        <h1>课表查询</h1>
      </div>
      <p class="head-note">
        共 <span class="num">{{ shown.length }}</span> 门课程 ·
        每节课 <span class="num">50</span> 分钟 ·
        作息 {{ periods[0].start }}–{{ periods[periods.length - 1].end }}
      </p>
    </header>

    <div class="weekbar" role="group" aria-label="按周次筛选">
      <span class="weekbar-label">周次</span>
      <button
        v-for="w in weeks"
        :key="w"
        type="button"
        class="week"
        :class="{ 'is-on': w === activeWeek, 'is-now': w === termMeta.week }"
        :aria-pressed="w === activeWeek"
        @click="activeWeek = w"
      >{{ w }}</button>
    </div>

    <TimetableGrid class="grid-box" :days="[1, 2, 3, 4, 5]" :items="shown" />

    <div v-if="!shown.length" class="empty">
      <p class="empty-title">第 {{ activeWeek }} 周没有课</p>
      <p class="empty-hint">换一周看看，或到"首页"问助手下次课是什么时候。</p>
    </div>

    <!-- 图例只列本周真正出现的学科，不摆满六色当装饰 -->
    <ul class="legend">
      <li v-for="d in visibleDomains" :key="d" class="legend-item">
        <span class="swatch" :class="'d-' + d" />
        {{ DOMAIN_LABELS[d] }}
        <span class="legend-count num">{{ countOf(d) }}</span>
      </li>
    </ul>

    <p class="foot-note">
      {{ weekdays[0] }}–{{ weekdays[4] }} 排课，周末无课。表格为仿真数据；要改选课或调课，请到教务办办理。
    </p>
    </template>
  </div>
</template>

<style scoped>
.page-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--rule);
}

.head h1 {
  margin-top: 8px;
}

.head-note {
  font-size: 12.5px;
  color: var(--faint);
}

/* 周次条：一行可滚的刻度，选中项只加墨色底，不动字色 */
.weekbar {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
  padding: 8px 0;
  border-bottom: 1px solid var(--rule);
}

.weekbar-label {
  flex: none;
  font-family: var(--display);
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--faint);
  margin-right: 6px;
}

.week {
  flex: none;
  font-family: var(--display);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  width: 28px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: none;
  color: var(--text);
  cursor: pointer;
  transition: background 0.14s ease, color 0.14s ease;
}

.week:hover {
  background: var(--paper);
}

.week.is-now {
  border-color: var(--rule-2);
}

.week.is-on {
  background: var(--ink);
  color: #fff;
}

.grid-box {
  border: 1px solid var(--rule);
  background: var(--card);
  border-radius: var(--r-md);
  padding: 6px 8px 10px;
}

.foot-note {
  font-size: 12.5px;
  color: var(--faint);
}

.legend {
  list-style: none;
  margin: -6px 0 0;
  padding: 0;
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--faint);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: var(--c-soft);
  border: 1px solid var(--c);
  border-left: 3px solid var(--c);
}

.legend-count {
  font-size: 12px;
  color: var(--ink-2);
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
