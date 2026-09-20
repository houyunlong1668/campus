<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ChatMessage } from '../../composables/useChatStream'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{ messages: ChatMessage[]; streaming: boolean }>()
const bottom = ref<HTMLElement | null>(null)
watch(
  () => props.messages.at(-1)?.text,
  async () => {
    await nextTick()
    bottom.value?.scrollIntoView({ behavior: 'smooth' })
  },
)
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
