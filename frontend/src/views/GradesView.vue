<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useResource } from '../composables/useResource'
import { creditsDoneOf, gpaOf, points, termMeta } from '../data/seed'
import type { GradeRow } from '../types'

const { data, loading, error, reload } = useResource<{ grades: GradeRow[] }>('/api/grades')
onMounted(reload)

const grades = computed(() => data.value?.grades ?? [])
const gpa = computed(() => gpaOf(grades.value))
const creditsDone = computed(() => creditsDoneOf(grades.value))
const failedCount = computed(() => grades.value.filter((g) => g.score < 60).length)
const best = computed(() =>
  grades.value.length ? grades.value.reduce((a, b) => (b.score > a.score ? b : a)) : null)
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
        <p class="eyebrow">{{ termMeta.semester }} · 已开放成绩 {{ grades.length }} 门</p>
        <h1>成绩查询</h1>
      </div>
      <p class="head-note">绩点为 5.0 分制：(分数 − 50) ÷ 10，90 分以上封顶 5.0</p>
    </header>

    <section class="summary">
      <div class="summary-main">
        <p class="eyebrow">平均绩点</p>
        <p class="gpa num">{{ gpa.toFixed(2) }}<span class="gpa-of">/ 5.0</span></p>
        <p class="gpa-note">
          已修 <span class="num">{{ creditsDone }}</span> 学分 ·
          专业要求 <span class="num">{{ termMeta.creditsRequired }}</span> 学分
        </p>
      </div>
      <dl class="summary-side">
        <div>
          <dt>不及格科目</dt>
          <dd class="num is-bad">{{ failedCount }}</dd>
        </div>
        <div>
          <dt>最高分</dt>
          <dd class="num">{{ best?.score ?? '—' }}</dd>
        </div>
        <div>
          <dt>在读学期</dt>
          <dd class="num">第 {{ termMeta.week }} 周</dd>
        </div>
      </dl>
    </section>

      <div v-if="!grades.length" class="empty">
        <p class="empty-title">还没有开放的成绩</p>
        <p class="empty-hint">成绩公布后会出现在这里。也可以问助手"我的绩点怎么样"。</p>
      </div>
      <section v-else class="panel">
      <table class="ledger">
        <caption>历学期成绩</caption>
        <thead>
          <tr>
            <th scope="col">课程</th>
            <th scope="col">课程代码</th>
            <th scope="col">学分</th>
            <th scope="col">成绩</th>
            <th scope="col">绩点</th>
            <th scope="col">学期</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="g in grades" :key="g.code">
            <td class="is-name">{{ g.name }}</td>
            <td class="code">{{ g.code }}</td>
            <td class="num">{{ g.credits }}</td>
            <td class="num" :class="{ 'is-bad': g.score < 60 }">{{ g.score || '—' }}</td>
            <td class="num">{{ points(g.score).toFixed(1) }}</td>
            <td>{{ g.term }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <p class="foot-note">
      成绩如有疑义，请在成绩公布后 5 个工作日内向任课教师申请复核。补考与重修安排见「补考重修」。
    </p>
    </template>
  </div>
</template>

<style scoped>
.head-note {
  font-size: 12.5px;
  color: var(--faint);
}

.summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 28px;
  align-items: center;
  padding: 20px 24px;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
}

.gpa {
  font-size: 56px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.02em;
  margin-top: 4px;
}

.gpa-of {
  font-size: 15px;
  font-weight: 400;
  color: var(--faint);
}

.gpa-note {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--faint);
}

.summary-side {
  display: grid;
  gap: 12px;
  margin: 0;
}

.summary-side div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--rule);
}

.summary-side div:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.summary-side dt {
  font-size: 13px;
  color: var(--faint);
}

.summary-side dd {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.is-bad {
  color: var(--seal);
}

.foot-note {
  font-size: 12.5px;
  color: var(--faint);
}

@media (max-width: 720px) {
  .summary {
    grid-template-columns: minmax(0, 1fr);
    gap: 20px;
  }

  .gpa {
    font-size: 44px;
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
