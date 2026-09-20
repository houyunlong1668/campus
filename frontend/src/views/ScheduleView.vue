<script setup lang="ts">
import { computed, ref } from 'vue'
import TimetableGrid from '../components/TimetableGrid.vue'
import { courses, periods, student, weekdays } from '../data/seed'

const activeWeek = ref(student.week)
const weeks = Array.from({ length: student.totalWeeks }, (_, i) => i + 1)

function inWeek(range: string, week: number): boolean {
  const [start, end] = range.split('-').map(Number)
  return week >= start && week <= (end || start)
}

const shown = computed(() => courses.filter((c) => inWeek(c.weeks, activeWeek.value)))
</script>

<template>
  <div class="page-body">
    <header class="head">
      <div>
        <p class="eyebrow">{{ student.semester }}</p>
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
        :class="{ 'is-on': w === activeWeek, 'is-now': w === student.week }"
        :aria-pressed="w === activeWeek"
        @click="activeWeek = w"
      >{{ w }}</button>
    </div>

    <TimetableGrid class="grid-box" :days="[1, 2, 3, 4, 5]" :items="shown" />

    <p class="foot-note">
      {{ weekdays[0] }}–{{ weekdays[4] }} 排课，周末无课。表格为仿真数据；要改选课或调课，请到教务办办理。
    </p>
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
</style>
