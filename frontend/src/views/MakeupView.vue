<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useResource } from '../composables/useResource'
import { termMeta } from '../data/seed'
import type { MakeupItem } from '../types'

const { data, loading, error, reload } = useResource<{ items: MakeupItem[] }>('/api/makeup')
onMounted(reload)

const items = computed(() => data.value?.items ?? [])
const statusStyle: Record<string, string> = {
  已报名: 'is-done',
  待缴费: 'is-wait',
  报名中: 'is-open',
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
        <p class="eyebrow">{{ termMeta.semester }} · 共 {{ items.length }} 项待处理</p>
        <h1>补考重修查询</h1>
      </div>
      <p class="head-note">补考安排由院教务统一下达，重修需在报名截止前完成缴费</p>
    </header>

    <div v-if="!items.length" class="empty">
      <p class="empty-title">没有需要办理的补考或重修</p>
      <p class="empty-hint">成绩全部通过。要核对分数可去「成绩查询」。</p>
    </div>
    <section v-else class="list">
      <article v-for="m in items" :key="m.code" class="item panel">
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
    </template>
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
