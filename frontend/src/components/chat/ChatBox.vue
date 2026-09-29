<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useAssistant } from '../../composables/useAssistant'
import { useChatStream } from '../../composables/useChatStream'
import MessageList from './MessageList.vue'

const { messages, streaming, send, abort } = useChatStream()
const { pending, takePending } = useAssistant()
const input = ref('')
const composing = ref(false)
const field = ref<HTMLInputElement | null>(null)

const placeholder = '这学期上什么课 / 查成绩 / 补考安排'

// 执行回放：POST /replay 拉最近一次执行的节点序列，只读展示不重执行
const replayOpen = ref(false)
const replayTrace = ref<{ steps: string[]; step_details: { node: string; latency_ms: number }[] } | null>(null)
// 模板侧取空安全的数组：replayTrace 为空或 step_details 空都落到这里走空态文案
const replayDetails = computed(() => replayTrace.value?.step_details ?? [])

async function replay() {
  try {
    const resp = await fetch('/replay', { method: 'POST', credentials: 'include' })
    replayTrace.value = resp.ok ? await resp.json() : { steps: [], step_details: [] }
  } catch {
    replayTrace.value = { steps: [], step_details: [] }
  }
  replayOpen.value = true
}

async function submit() {
  const text = input.value.trim()
  // 输入法组合态的 Enter 是在选词，不是发送
  if (!text || streaming.value || composing.value) return
  input.value = ''
  await send(text)
}

function fill(text: string) {
  if (!text) return
  input.value = text
  nextTick(() => field.value?.focus())
}

onMounted(() => fill(takePending()))
watch(pending, (text) => fill(text))
</script>

<template>
  <div class="chat-box">
    <div class="tool-bar">
      <button type="button" class="act is-replay" @click="replay">回放上次执行</button>
    </div>

    <details v-if="replayOpen" class="replay">
      <summary class="replay-summary">执行回放</summary>
      <table v-if="replayDetails.length" class="replay-table">
        <thead>
          <tr><th>节点</th><th>耗时 ms</th></tr>
        </thead>
        <tbody>
          <tr v-for="(d, i) in replayDetails" :key="i">
            <td class="code">{{ d.node }}</td>
            <td class="code">{{ d.latency_ms }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="replay-empty">还没有可回放的执行记录</p>
    </details>

    <MessageList :messages="messages" />

    <form class="input-row" @submit.prevent="submit">
      <input
        ref="field"
        v-model="input"
        class="field"
        type="text"
        :placeholder="placeholder"
        autocomplete="off"
        :disabled="streaming"
        @compositionstart="composing = true"
        @compositionend="composing = false"
      />
      <button v-if="!streaming" type="submit" class="act">发送</button>
      <button v-else type="button" class="act is-stop" @click="abort">停止</button>
    </form>
  </div>
</template>

<style scoped>
.chat-box {
  display: flex;
  flex-direction: column;
  height: 412px;
  min-height: 0;
}

.input-row {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--rule);
  background: var(--paper);
}

/* 头部工具区：与底部输入行同一条纸带，上下对称框住消息区 */
.tool-bar {
  display: flex;
  justify-content: flex-end;
  padding: 8px 12px;
  border-bottom: 1px solid var(--rule);
  background: var(--paper);
}

.act.is-replay {
  padding: 5px 12px;
  font-size: 12.5px;
  background: var(--card);
  color: var(--ink-2);
}

.act.is-replay:hover {
  background: var(--card);
  color: var(--seal);
}

/* 回放面板：只读明细，行序即执行序 */
.replay {
  padding: 8px 12px 10px;
  border-bottom: 1px solid var(--rule);
  background: var(--card);
}

.replay-summary {
  cursor: pointer;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: var(--ink-2);
  user-select: none;
}

.replay-summary:hover {
  color: var(--seal);
}

.replay-table {
  width: 100%;
  margin-top: 7px;
  border-collapse: collapse;
  font-size: 12.5px;
}

.replay-table th {
  text-align: left;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--faint);
  padding: 3px 0;
  border-bottom: 1px solid var(--rule);
}

.replay-table td {
  padding: 3px 0;
  border-bottom: 1px solid var(--rule);
  color: var(--ink);
}

.replay-table tr:last-child td {
  border-bottom: none;
}

.replay-empty {
  margin: 7px 0 0;
  font-size: 12px;
  color: var(--faint);
}

.field {
  flex: 1;
  min-width: 0;
  font: inherit;
  font-size: 14px;
  color: var(--ink);
  background: var(--card);
  border: 1px solid var(--rule-2);
  border-radius: var(--r-sm);
  padding: 8px 10px;
  transition: border-color 0.16s ease;
}

.field::placeholder {
  color: var(--faint);
}

.field:focus {
  outline: none;
  border-color: var(--ink);
}

.field:disabled {
  background: var(--paper);
  color: var(--faint);
}

.act {
  flex: none;
  font: inherit;
  font-size: 13.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: #fff;
  background: var(--ink);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  padding: 8px 16px;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.act:hover {
  background: var(--seal);
  border-color: var(--seal);
}

.act.is-stop {
  background: var(--card);
  color: var(--ink-2);
}

.act.is-stop:hover {
  color: var(--seal);
  border-color: var(--seal);
}
</style>
