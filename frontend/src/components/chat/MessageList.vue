<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { ChatMessage } from '../../composables/useChatStream'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{ messages: ChatMessage[] }>()
const bottom = ref<HTMLElement | null>(null)

// 只跟 text 长度会漏掉状态条/卡片/错误到达时的滚动
const tail = computed(() => {
  const last = props.messages.at(-1)
  return `${props.messages.length}|${last?.text.length ?? 0}|${last?.toolCall ? 1 : 0}|${last?.navCard ? 1 : 0}|${last?.error ? 1 : 0}`
})

watch(tail, async () => {
  await nextTick()
  bottom.value?.scrollIntoView({ behavior: 'smooth' })
})
</script>

<template>
  <div class="message-list">
    <MessageBubble v-for="m in messages" :key="m.id" :message="m" />
    <div ref="bottom" />
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}
</style>
