<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const { login } = useAuth()
const route = useRoute()
const router = useRouter()

const studentId = ref('20230001')
const password = ref('')
const busy = ref(false)
const error = ref('')
const cooldown = ref(0)
const composing = ref(false)

let timer: number | undefined
function startCooldown(seconds: number) {
  window.clearInterval(timer)
  cooldown.value = seconds
  timer = window.setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0) window.clearInterval(timer)
  }, 1000)
}
onUnmounted(() => window.clearInterval(timer))

const disabled = computed(() => busy.value || cooldown.value > 0)
const buttonLabel = computed(() =>
  cooldown.value > 0 ? `请 ${cooldown.value} 秒后再试`
    : busy.value ? '登录中…' : '登录')

async function submit() {
  // 输入法组合态的 Enter 是在选词，不是提交
  if (disabled.value || composing.value) return
  error.value = ''
  busy.value = true
  const r = await login(studentId.value.trim(), password.value)
  busy.value = false

  if (r.ok) {
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    router.replace(next)
    return
  }
  error.value = r.message
  // 失败后学号保留不清空，只重输密码
  password.value = ''
  if (r.code === 'too_many_attempts') startCooldown(60)
}
</script>

<template>
  <div class="login">
    <form class="card" @submit.prevent="submit">
      <p class="eyebrow">南岭大学 · 教务系统</p>
      <h1>学生登录</h1>

      <p v-if="error" class="error" role="status" aria-live="polite">{{ error }}</p>

      <label for="sid">学号</label>
      <input id="sid" v-model="studentId" class="field" type="text"
             autocomplete="username" inputmode="numeric" maxlength="32" />

      <label for="pw">密码</label>
      <input id="pw" v-model="password" class="field" type="password"
             autocomplete="current-password" maxlength="128"
             @compositionstart="composing = true" @compositionend="composing = false" />

      <button class="submit" type="submit" :disabled="disabled">{{ buttonLabel }}</button>
      <p class="hint">仿真环境账号 20230001 / 20230002 / 20230007，密码均为 demo1234</p>
    </form>
  </div>
</template>

<style scoped>
.login {
  flex: 1;
  display: grid;
  place-items: center;
  padding: 24px 0 48px;
}

.card {
  width: 380px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 26px 24px;
  box-shadow: var(--shadow);
}

.card h1 {
  margin: 6px 0 18px;
  font-size: 26px;
}

label {
  font-family: var(--display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--faint);
  margin-bottom: 5px;
}

.field {
  font: inherit;
  font-size: 15px;
  color: var(--ink);
  background: var(--card);
  border: 1px solid var(--rule-2);
  border-radius: var(--r-sm);
  padding: 9px 11px;
  margin-bottom: 16px;
}

.field:focus {
  outline: none;
  border-color: var(--ink);
}

.submit {
  font: inherit;
  font-size: 15px;
  font-weight: 500;
  color: #fff;
  background: var(--ink);
  border: 1px solid var(--ink);
  border-radius: var(--r-sm);
  padding: 10px;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.submit:hover:not(:disabled) {
  background: var(--seal);
  border-color: var(--seal);
}

.submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.error {
  font-size: 13px;
  color: var(--seal);
  border-left: 2px solid var(--seal);
  padding-left: 9px;
  margin-bottom: 16px;
}

.hint {
  margin-top: 14px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--faint);
}
</style>
