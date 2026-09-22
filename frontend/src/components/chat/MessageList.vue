<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { ChatMessage } from '../../composables/useChatStream'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{ messages: ChatMessage[] }>()
const bottom = ref<HTMLElement | null>(null)

// 只跟 text 长度会漏掉状态条/卡片/错误到达时的滚动
const tail = computed(() => {
  const last = props.messages.at(-1)
  return `${props.messages.length}|${last?.text.length ?? 0}|${last?.toolCall ? 1 : 0}|${last?.navCard ? 1 : 0}|${last?.error ? 1 : 0}|${last?.clarify ? 1 : 0}|${last?.sqlResult ? 1 : 0}`
})

watch(tail, async () => {
  await nextTick()
  bottom.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
})
</script>

<template>
  <div class="message-list">
    <div v-if="!messages.length" class="start">
      <p class="start-title">想查什么？</p>
      <p class="start-hint">
        问一句课程、成绩、补考或图书的事，助手会定位到对应教务页面并给出跳转。
      </p>
      <p class="start-eg">例如：这学期上什么课</p>
    </div>

    <MessageBubble v-for="m in messages" :key="m.id" :message="m" />
    <div ref="bottom" />
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.start {
  margin: auto 0;
  padding: 18px 4px;
}

.start-title {
  font-family: var(--display);
  font-size: 17px;
  font-weight: 600;
  color: var(--ink);
}

.start-hint {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  max-width: 30ch;
}

.start-eg {
  margin-top: 12px;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--faint);
  border-left: 2px solid var(--rule-2);
  padding-left: 8px;
}
</style>
