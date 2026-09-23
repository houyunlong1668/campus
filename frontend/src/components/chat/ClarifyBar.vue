<script setup lang="ts">
import type { ClarifyEvent } from '../../types'
import { useChatStream } from '../../composables/useChatStream'

const props = defineProps<{ clarify: ClarifyEvent }>()
const { send, streaming } = useChatStream()

// 直接用模块级单例的 send：中间三层组件逐层 emit 只为传一个回调，
// 而 useChatStream 本来就是设计成跨组件存活的单例（悬浮球卸载也不断流）
function choose(label: string) {
  if (!streaming.value) void send(label)
}
</script>

<template>
  <div class="clarify">
    <p class="clarify-q">{{ props.clarify.question }}</p>
    <div class="clarify-opts">
      <button
        v-for="o in props.clarify.options"
        :key="o.label"
        type="button"
        class="clarify-opt"
        :disabled="streaming"
        @click="choose(o.label)"
      >
        {{ o.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.clarify {
  border: 1px dashed var(--rule-2);
  border-radius: var(--r-sm);
  background: var(--paper);
  padding: 8px 10px;
}

.clarify-q {
  font-size: 13px;
  color: var(--text);
}

.clarify-opts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.clarify-opt {
  font: inherit;
  font-size: 12.5px;
  padding: 5px 12px;
  color: var(--ink);
  background: var(--card);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.clarify-opt:hover:not(:disabled) {
  color: #fff;
  background: var(--seal);
  border-color: var(--seal);
}

.clarify-opt:disabled {
  color: var(--faint);
  border-color: var(--rule-2);
  cursor: default;
}
</style>
