<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useAssistant } from '../../composables/useAssistant'
import { useChatStream } from '../../composables/useChatStream'
import MessageList from './MessageList.vue'

const { messages, streaming, send, abort } = useChatStream()
const { pending, takePending } = useAssistant()
const input = ref('')
const composing = ref(false)
const field = ref<HTMLInputElement | null>(null)

const placeholder = '这学期上什么课 / 查成绩 / 补考安排'

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
