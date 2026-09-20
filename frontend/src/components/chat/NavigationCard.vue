<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { NavCard } from '../../types'

const props = defineProps<{ card: NavCard }>()
const router = useRouter()

function go() {
  router.push(props.card.path) // 验收关键：跳转必须真实发生
}
</script>

<template>
  <el-card class="nav-card" shadow="hover" @click="go">
    <div class="title">{{ card.title }}</div>
    <div class="reason">{{ card.reason }}</div>
    <div class="path">{{ card.path }}</div>
  </el-card>
</template>

<style scoped>
.nav-card {
  margin-top: 8px;
  cursor: pointer;
}
.title {
  font-weight: 600;
  margin-bottom: 4px;
}
.reason {
  font-size: 13px;
  color: #606266;
}
.path {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
