<script setup lang="ts">
import { ref } from 'vue'
import ChatBox from './ChatBox.vue'

const open = ref(false)
const showDisclaimer = ref(true) // 每次会话首次展开显示
</script>

<template>
  <div class="floating-ball">
    <el-button v-if="!open" circle class="ball" @click="open = true">问</el-button>
    <div v-else class="panel">
      <div class="panel-header">
        <span>校园助手</span>
        <el-button text @click="open = false">收起</el-button>
      </div>
      <el-alert
        v-if="showDisclaimer"
        type="info"
        :closable="true"
        title="演示环境声明"
        description="本助手由 AI 驱动，当前为课程项目仿真数据，仅供参考；跳转页面为本地仿真校园站。"
        @close="showDisclaimer = false"
        class="disclaimer"
      />
      <ChatBox />
    </div>
  </div>
</template>

<style scoped>
.floating-ball {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1000;
}
.ball {
  width: 56px;
  height: 56px;
  font-size: 18px;
}
.panel {
  width: 380px;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
  font-weight: 600;
}
.disclaimer {
  margin: 8px 12px 0;
}
</style>
