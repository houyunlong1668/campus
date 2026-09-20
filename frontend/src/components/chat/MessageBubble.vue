<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '../../composables/useChatStream'
import { md } from '../../lib/markdown'
import NavigationCard from './NavigationCard.vue'

const props = defineProps<{ message: ChatMessage }>()
const rendered = computed(() => md.render(props.message.text))
</script>

<template>
  <div class="bubble" :class="message.role">
    <!-- 工具调用是这台机器的心跳，单独占一行读数 -->
    <div v-if="message.toolCall" class="tool" :class="{ 'is-fail': !message.toolCall.ok }">
      <span class="tool-mark" />
      <span class="tool-name code">{{ message.toolCall.name }}</span>
      <span class="tool-state">{{ message.toolCall.ok ? '命中' : '未命中' }}</span>
      <span class="tool-ms code">{{ message.toolCall.latencyMs }}ms</span>
    </div>

    <div v-if="message.text" class="markdown-body" v-html="rendered" />

    <NavigationCard v-if="message.navCard" :card="message.navCard" />

    <p v-if="message.error" class="error">{{ message.error }}</p>
  </div>
</template>

<style scoped>
.bubble {
  max-width: 92%;
}

.bubble.user {
  align-self: flex-end;
  background: var(--ink);
  color: #fff;
  border-radius: var(--r-md);
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.55;
}

.bubble.assistant {
  align-self: stretch;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 10px 12px;
}

.tool {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: var(--ink-2);
  background: var(--paper);
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
  padding: 4px 0;
}

.tool-mark {
  width: 5px;
  height: 5px;
  flex: none;
  background: var(--jade);
}

.tool.is-fail .tool-mark {
  background: var(--seal);
}

.tool-name {
  color: var(--ink);
  font-weight: 600;
}

.tool-state {
  color: var(--faint);
}

.tool-ms {
  margin-left: auto;
  color: var(--faint);
}

.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
}

.markdown-body :deep(p) {
  margin: 0 0 6px;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(code) {
  font-family: var(--mono);
  font-size: 12.5px;
  background: var(--paper);
  padding: 1px 4px;
  border: 1px solid var(--rule);
}

.markdown-body :deep(pre) {
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  padding: 10px;
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  border: none;
  background: none;
  padding: 0;
}

.markdown-body :deep(strong) {
  color: var(--ink);
}

.markdown-body :deep(a) {
  border-bottom: 1px solid var(--rule-2);
}

.error {
  font-size: 12.5px;
  color: var(--seal);
  border-left: 2px solid var(--seal);
  padding-left: 8px;
}
</style>
