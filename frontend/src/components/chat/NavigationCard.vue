<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { NavCard } from '../../types'

const props = defineProps<{ card: NavCard }>()
const router = useRouter()

function go() {
  router.push(props.card.path) // 验收关键：跳转必须真实发生
}
</script>

<template>
  <button type="button" class="nav-card" :aria-label="`打开${card.title}`" @click="go">
    <span class="nav-main">
      <span class="nav-title">{{ card.title }}</span>
      <span class="nav-reason">{{ card.reason }}</span>
    </span>
    <span class="nav-side">
      <span class="nav-path code">{{ card.path }}</span>
      <span class="nav-go" aria-hidden="true">→</span>
    </span>
  </button>
</template>

<style scoped>
/* 做成一张可点的单据，而不是一张营销卡片 */
.nav-card {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  text-align: left;
  font: inherit;
  cursor: pointer;
  background: var(--paper);
  border: 1px solid var(--rule-2);
  border-left: 3px solid var(--ink);
  border-radius: var(--r-sm);
  padding: 9px 12px;
  transition: border-color 0.16s ease, background 0.16s ease;
}

.nav-card:hover {
  background: var(--card);
  border-left-color: var(--seal);
}

.nav-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.nav-title {
  font-family: var(--display);
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
}

.nav-reason {
  font-size: 11.5px;
  color: var(--faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.nav-path {
  color: var(--ink-2);
}

.nav-go {
  color: var(--faint);
  transition: transform 0.16s ease, color 0.16s ease;
}

.nav-card:hover .nav-go {
  color: var(--seal);
  transform: translateX(3px);
}

@media (max-width: 420px) {
  .nav-path {
    display: none;
  }
}
</style>
