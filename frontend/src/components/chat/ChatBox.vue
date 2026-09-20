<script setup lang="ts">
import { ref } from 'vue'
import { useChatStream } from '../../composables/useChatStream'
import MessageList from './MessageList.vue'

const { messages, streaming, send, abort } = useChatStream()
const input = ref('')
const placeholder = '试试：这学期上什么课 / 查成绩 / 补考安排 / 图书馆'

async function submit() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  input.value = ''
  await send(text)
}
</script>

<template>
  <div class="chat-box">
    <MessageList :messages="messages" :streaming="streaming" />
    <div class="input-row">
      <el-input
        v-model="input"
        :placeholder="placeholder"
        :disabled="streaming"
        @keyup.enter="submit"
      />
      <el-button v-if="!streaming" type="primary" @click="submit">发送</el-button>
      <el-button v-else @click="abort">停止</el-button>
    </div>
  </div>
</template>

<style scoped>
.chat-box {
  display: flex;
  flex-direction: column;
  height: 420px;
}
.input-row {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid #ebeef5;
}
</style>
