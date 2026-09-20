<script setup lang="ts">
import { useAssistant } from '../../composables/useAssistant'
import ChatBox from './ChatBox.vue'

const { open, toggle } = useAssistant()
</script>

<template>
  <div class="assistant">
    <Transition name="panel">
      <div v-if="open" class="panel" role="dialog" aria-label="校园助手">
        <div class="panel-head">
          <span class="panel-title">校园助手</span>
          <span class="panel-sub">调用教务页面清单</span>
          <button type="button" class="collapse" @click="toggle(false)">收起</button>
        </div>

        <p class="disclaimer">
          演示环境：AI 生成内容仅供参考，页面数据为课程项目仿真数据。
        </p>

        <ChatBox />
      </div>
    </Transition>

    <button
      v-if="!open"
      type="button"
      class="ball"
      aria-label="打开校园助手"
      @click="toggle(true)"
    >
      <span class="ball-glyph">问</span>
    </button>
  </div>
</template>

<style scoped>
.assistant {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
}

/* 印章式悬浮钮：墨蓝实心 + 白字，hover 才露朱红外环 */
.ball {
  width: 54px;
  height: 54px;
  border-radius: 50%;
  border: 1px solid var(--ink);
  background: var(--ink);
  color: #fff;
  cursor: pointer;
  display: grid;
  place-items: center;
  box-shadow: 0 6px 18px -6px rgba(22, 35, 58, 0.5);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.ball:hover {
  transform: translateY(-2px);
  border-color: var(--seal);
  box-shadow: 0 10px 22px -8px rgba(176, 56, 43, 0.45);
}

.ball-glyph {
  font-family: var(--display);
  font-size: 21px;
  font-weight: 600;
}

.panel {
  width: 392px;
  max-width: calc(100vw - 32px);
  display: flex;
  flex-direction: column;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  box-shadow: 0 18px 40px -18px rgba(22, 35, 58, 0.4);
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--rule);
}

.panel-title {
  font-family: var(--display);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: 0.04em;
}

.panel-sub {
  flex: 1;
  font-size: 11.5px;
  color: var(--faint);
}

.collapse {
  font: inherit;
  font-size: 12.5px;
  border: none;
  background: none;
  color: var(--faint);
  cursor: pointer;
  padding: 2px 0;
}

.collapse:hover {
  color: var(--seal);
}

.disclaimer {
  margin: 0;
  padding: 8px 14px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--ink-2);
  background: var(--paper);
  border-bottom: 1px solid var(--rule);
  border-left: 2px solid var(--seal);
}

.panel-enter-active,
.panel-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (max-width: 720px) {
  .assistant {
    right: 14px;
    bottom: 14px;
  }
}
</style>
