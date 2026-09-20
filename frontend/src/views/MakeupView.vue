<script setup lang="ts">
import { makeup, student } from '../data/seed'

const statusStyle: Record<string, string> = {
  已报名: 'is-done',
  待缴费: 'is-wait',
  报名中: 'is-open',
}
</script>

<template>
  <div class="page-body">
    <header class="page-head">
      <div>
        <p class="eyebrow">{{ student.semester }} · 共 {{ makeup.length }} 项待处理</p>
        <h1>补考重修查询</h1>
      </div>
      <p class="head-note">补考安排由院教务统一下达，重修需在报名截止前完成缴费</p>
    </header>

    <section class="list">
      <article v-for="m in makeup" :key="m.code" class="item panel">
        <div class="item-top">
          <span class="kind" :class="m.type === '补考' ? 'is-makeup' : 'is-again'">{{ m.type }}</span>
          <h2 class="item-title">{{ m.course }}</h2>
          <span class="status" :class="statusStyle[m.status]">{{ m.status }}</span>
        </div>

        <p class="reason">{{ m.reason }}</p>

        <dl class="facts">
          <div>
            <dt>课程代码</dt>
            <dd class="code">{{ m.code }}</dd>
          </div>
          <div>
            <dt>{{ m.type === '补考' ? '补考时间' : '时间安排' }}</dt>
            <dd>{{ m.when }}</dd>
          </div>
          <div>
            <dt>地点</dt>
            <dd>{{ m.place }}</dd>
          </div>
          <div v-if="m.seats">
            <dt>重修名额</dt>
            <dd>{{ m.seats }}</dd>
          </div>
        </dl>
      </article>
    </section>

    <section class="notice panel">
      <h3>办理须知</h3>
      <ol>
        <li>补考不通过的课程转入重修，重修成绩按实际分数记载。</li>
        <li>考试须携带学生证与身份证，提前 15 分钟到场。</li>
        <li>缴费截止后未支付的报名自动作废，不另设补报。</li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.head-note {
  font-size: 12.5px;
  color: var(--faint);
}

.list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.item {
  padding: 16px 20px;
  border-left: 3px solid var(--ink);
}

.item-top {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.item-title {
  flex: 1;
  min-width: 12ch;
}

.kind {
  font-family: var(--display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  padding: 2px 7px;
  border-radius: 2px;
  border: 1px solid var(--rule-2);
  color: var(--ink-2);
}

.kind.is-makeup {
  border-color: var(--seal);
  color: var(--seal);
}

.status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 100px;
  background: var(--paper);
  color: var(--ink-2);
}

.status.is-done {
  background: var(--jade-veil);
  color: var(--jade);
}

.status.is-wait {
  background: var(--seal-veil);
  color: var(--seal);
}

.reason {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text);
}

.facts {
  margin: 14px 0 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 12px 24px;
  padding-top: 12px;
  border-top: 1px dashed var(--rule-2);
}

.facts div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.facts dt {
  font-size: 11.5px;
  color: var(--faint);
}

.facts dd {
  margin: 0;
  font-size: 13.5px;
  color: var(--ink);
}

.notice {
  padding: 16px 20px;
  background: var(--paper);
}

.notice h3 {
  font-size: 14px;
}

.notice ol {
  margin: 10px 0 0;
  padding-left: 20px;
  display: grid;
  gap: 6px;
  font-size: 13px;
  color: var(--text);
}
</style>
