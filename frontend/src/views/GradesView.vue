<script setup lang="ts">
import { computed } from 'vue'
import { creditsDone, failedCount, gpa, grades, points, student } from '../data/seed'

const best = computed(() => grades.reduce((a, b) => (b.score > a.score ? b : a)))
</script>

<template>
  <div class="page-body">
    <header class="page-head">
      <div>
        <p class="eyebrow">{{ student.semester }} · 已开放成绩 {{ grades.length }} 门</p>
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
          专业要求 <span class="num">{{ student.creditsRequired }}</span> 学分
        </p>
      </div>
      <dl class="summary-side">
        <div>
          <dt>不及格科目</dt>
          <dd class="num is-bad">{{ failedCount }}</dd>
        </div>
        <div>
          <dt>最高分</dt>
          <dd class="num">{{ best.score }}</dd>
        </div>
        <div>
          <dt>在读学期</dt>
          <dd class="num">第 {{ student.week }} 周</dd>
        </div>
      </dl>
    </section>

    <section class="panel">
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
</style>
