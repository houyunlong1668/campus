<script setup lang="ts">
import { computed } from 'vue'
import { libraryStats, loans, student } from '../data/seed'

const sorted = computed(() => [...loans].sort((a, b) => a.daysLeft - b.daysLeft))
const seatPct = computed(() => Math.round((libraryStats.seatsOpen / libraryStats.seatsTotal) * 100))

function dayLabel(d: number): string {
  if (d < 0) return `已逾期 ${Math.abs(d)} 天`
  if (d === 0) return '今天应还'
  if (d <= 3) return `${d} 天后应还`
  return `剩 ${d} 天`
}
</script>

<template>
  <div class="page-body">
    <header class="page-head">
      <div>
        <p class="eyebrow">{{ student.semester }} · 图书馆</p>
        <h1>图书馆服务</h1>
      </div>
      <p class="head-note">
        可借 <span class="num">{{ libraryStats.quota - libraryStats.borrowed }}</span> / {{ libraryStats.quota }} 册 ·
        逾期罚款 <span class="num">{{ libraryStats.fine }}</span>
      </p>
    </header>

    <section class="panel">
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
          {{ libraryStats.seatsOpen }}<span class="seat-of">/ {{ libraryStats.seatsTotal }}</span>
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
</style>
