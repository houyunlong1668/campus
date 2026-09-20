<script setup lang="ts">
import { computed } from 'vue'
import { md } from '../../lib/markdown'
import type { ChatMessage } from '../../composables/useChatStream'
import NavigationCard from './NavigationCard.vue'

const props = defineProps<{ message: ChatMessage }>()

const rendered = computed(() => md.render(props.message.text))
</script>

<template>
  <div class="bubble" :class="message.role">
    <div v-if="message.toolCall" class="tool-call">
      正在调用 {{ message.toolCall.name }}（{{ message.toolCall.latencyMs }}ms）{{
        message.toolCall.ok ? '' : ' — 失败，已降级回答'
      }}
    </div>
    <div v-if="message.text" class="markdown-body" v-html="rendered" />
    <NavigationCard v-if="message.navCard" :card="message.navCard" />
    <div v-if="message.error" class="error">{{ message.error }}</div>
  </div>
</template>

<style scoped>
.bubble {
  max-width: 85%;
  padding: 8px 12px;
  border-radius: 10px;
  margin: 6px 0;
  background: #f4f4f5;
}
.bubble.user {
  margin-left: auto;
  background: #ecf5ff;
}
.tool-call {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.markdown-body :deep(p) {
  margin: 4px 0;
}
.error {
  color: #f56c6c;
  font-size: 13px;
  margin-top: 4px;
}
</style>
