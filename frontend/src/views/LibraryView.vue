<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useResource } from '../composables/useResource'
import { libraryMeta, termMeta } from '../data/seed'
import type { LoanItem } from '../types'

const { data, loading, error, reload } = useResource<{ items: LoanItem[] }>('/api/loans')
onMounted(reload)

const items = computed(() => data.value?.items ?? [])
const sorted = computed(() => [...items.value].sort((a, b) => a.daysLeft - b.daysLeft))
const borrowed = computed(() => items.value.length)
const overdueCount = computed(() => items.value.filter((l) => l.daysLeft < 0).length)
const seatPct = computed(() =>
  Math.round((libraryMeta.seatsOpen / libraryMeta.seatsTotal) * 100))

function dayLabel(d: number): string {
  if (d < 0) return `已逾期 ${Math.abs(d)} 天`
  if (d === 0) return '今天应还'
  if (d <= 3) return `${d} 天后应还`
  return `剩 ${d} 天`
}
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
    <header class="page-head">
      <div>
        <p class="eyebrow">{{ termMeta.semester }} · 图书馆</p>
        <h1>图书馆服务</h1>
      </div>
      <p class="head-note">
        可借 <span class="num">{{ libraryMeta.quota - borrowed }}</span> / {{ libraryMeta.quota }} 册 ·
        在借 <span class="num">{{ borrowed }}</span> 册 ·
        逾期 <span class="num">{{ overdueCount }}</span> 册 ·
        逾期罚款 <span class="num">{{ libraryMeta.fine }}</span>
      </p>
    </header>

      <div v-if="!items.length" class="empty">
        <p class="empty-title">没有在借的图书</p>
        <p class="empty-hint">全部归还完毕。要查馆藏可以问助手"图书馆有哪些书"。</p>
      </div>
      <section v-else class="panel">
      <table class="ledger">
        <caption>在借的书（按应还日排序）</caption>
        <thead>
          <tr>
            <th scope="col">题名</th>
            <th scope="col">索书号</th>
            <th scope="col">架位</th>
            <th scope="col">应还日期</th>
            <th scope="col">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in sorted" :key="l.callNo">
            <td class="is-name">{{ l.title }}</td>
            <td class="code">{{ l.callNo }}</td>
            <td>{{ l.place }}</td>
            <td>{{ l.due }}</td>
            <td>
              <span class="state" :class="{ 'is-late': l.daysLeft < 0, 'is-soon': l.daysLeft >= 0 && l.daysLeft <= 3 }">
                {{ dayLabel(l.daysLeft) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="side">
      <div class="seat panel">
        <p class="eyebrow">自修座位</p>
        <p class="seat-num num">
          {{ libraryMeta.seatsOpen }}<span class="seat-of">/ {{ libraryMeta.seatsTotal }}</span>
        </p>
        <p class="seat-label">当前空位</p>
        <div class="bar"><span :style="{ width: seatPct + '%' }" /></div>
      </div>

      <div class="rules panel">
        <h3>借阅规则</h3>
        <ul>
          <li>本科生同期可借 10 册，借期 30 天，可续借一次。</li>
          <li>逾期每册每天 0.10 元，累计超 10 元暂停借阅。</li>
          <li>三楼自然科学区支持开架阅览，离场前到服务台办理借出。</li>
        </ul>
      </div>
    </section>
    </template>
  </div>
</template>

<style scoped>
.head-note {
  font-size: 12.5px;
  color: var(--faint);
}

.state {
  font-size: 12.5px;
  color: var(--text);
}

.state.is-soon {
  color: var(--ink);
  font-weight: 500;
}

.state.is-late {
  color: var(--seal);
  font-weight: 500;
}

.side {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 14px;
  align-items: stretch;
}

.seat {
  padding: 16px 20px;
}

.seat-num {
  font-size: 40px;
  font-weight: 600;
  line-height: 1;
  margin-top: 6px;
}

.seat-of {
  font-size: 15px;
  font-weight: 400;
  color: var(--faint);
}

.seat-label {
  font-size: 12.5px;
  color: var(--faint);
  margin-top: 4px;
}

.bar {
  height: 3px;
  margin-top: 14px;
  background: var(--rule);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--jade);
  transition: width 0.5s ease;
}

.rules {
  padding: 16px 20px;
  background: var(--paper);
}

.rules h3 {
  font-size: 14px;
}

.rules ul {
  margin: 10px 0 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: var(--text);
}

@media (max-width: 720px) {
  .side {
    grid-template-columns: minmax(0, 1fr);
  }
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
