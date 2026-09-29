<script setup lang="ts">
import { ref } from 'vue'
import type { ConfirmCardEvent } from '../../types'

const props = defineProps<{ card: ConfirmCardEvent }>()
const state = ref<'idle' | 'loading' | 'done' | 'error'>('idle')
const resultText = ref('')

async function confirm() {
  if (state.value !== 'idle') return
  state.value = 'loading'
  try {
    const resp = await fetch('/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ action_id: props.card.action_id }),
    })
    if (resp.status === 401) {
      resultText.value = '登录已过期，请重新登录'
    } else if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      resultText.value = body?.detail ?? '确认失败，请重新发起对话'
    } else {
      const body = await resp.json()
      const r = body.result
      resultText.value = r.status === 'already' ? '这门课之前已报名，无需重复提交'
        : `报名成功：${r.course}（${r.kind}）`
    }
    state.value = resp?.ok ? 'done' : 'error'
  } catch {
    resultText.value = '网络异常，请稍后重试'
    state.value = 'error'
  }
}
</script>

<template>
  <div class="confirm-card" data-testid="confirm-card">
    <p class="confirm-card__title">{{ card.title }}</p>
    <p class="confirm-card__summary">{{ card.summary }}</p>
    <button type="button" :disabled="state !== 'idle'" @click="confirm">
      {{ state === 'loading' ? '确认中…' : '确认报名' }}
    </button>
    <p
      v-if="resultText"
      class="confirm-card__result"
      :class="state === 'done' ? 'is-done' : 'is-error'"
      data-testid="confirm-result"
    >{{ resultText }}</p>
  </div>
</template>

<style scoped>
/* 单据式确认卡：跟 NavigationCard.vue 同一套卡片语言——
   纸底 + 左侧墨蓝实线（hover 朱红）+ display 标题，不发明第二套 */
.confirm-card {
  display: flex;
  flex-direction: column;
  gap: 7px;
  background: var(--paper);
  border: 1px solid var(--rule-2);
  border-left: 3px solid var(--ink);
  border-radius: var(--r-sm);
  padding: 9px 12px;
}

.confirm-card__title {
  margin: 0;
  font-family: var(--display);
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
}

.confirm-card__summary {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text);
}

.confirm-card button {
  align-self: flex-start;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: #fff;
  background: var(--ink);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  padding: 5px 14px;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.confirm-card button:hover:not(:disabled) {
  background: var(--seal);
  border-color: var(--seal);
}

/* 一次性语义：确认过（成功或失败）就永久禁点，不给第二次机会 */
.confirm-card button:disabled {
  background: var(--paper);
  border-color: var(--rule-2);
  color: var(--faint);
  cursor: not-allowed;
}

.confirm-card__result {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
}

.confirm-card__result.is-done {
  color: var(--jade);
  border-left: 2px solid var(--jade);
  padding-left: 8px;
}

.confirm-card__result.is-error {
  color: var(--seal);
  border-left: 2px solid var(--seal);
  padding-left: 8px;
}
</style>
