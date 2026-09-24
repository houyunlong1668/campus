<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FloatingBall from './components/chat/FloatingBall.vue'
import { useAuth } from './composables/useAuth'
import { termMeta } from './data/seed'

const route = useRoute()
const router = useRouter()
// 只读不取：/auth/me 由 router.beforeEach 的 bootstrap 负责，这里再调一次会重复打后端
const { user, logout } = useAuth()
const isLogin = computed(() => route.path === '/login')

// 守卫只在导航时生效：退出后必须显式跳登录页，否则会停在原页面变成"未登录却在看着数据"
async function onLogout() {
  await logout()
  router.push('/login')
}
const tabs = [
  { to: '/', label: '首页' },
  { to: '/academic/schedule', label: '课表' },
  { to: '/academic/grades', label: '成绩' },
  { to: '/academic/makeup', label: '补考重修' },
  { to: '/library', label: '图书馆' },
]

const todayLabel = computed(() => {
  const d = new Date()
  const week = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'][d.getDay()]
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日 ${week}`
})
</script>

<template>
  <div class="shell">
    <header class="signplate">
      <div class="signplate-inner">
        <div class="brand">
          <span class="crest">蹲</span>
          <span class="brand-text">
            <strong>家里蹲大学</strong>
            <em>教务系统 · 学生端</em>
          </span>
        </div>
        <div class="meta" v-if="!isLogin">
          <span class="meta-item">{{ todayLabel }}</span>
          <span class="meta-sep" />
          <span class="meta-item">第 {{ termMeta.week }} 周 / 共 {{ termMeta.totalWeeks }} 周</span>
          <span class="meta-sep" />
          <span class="who">
            <span class="who-name">{{ user?.name ?? '—' }}</span>
            <span class="code who-id">{{ user?.student_id ?? '未登录' }}</span>
            <button type="button" class="logout" @click="onLogout">退出</button>
          </span>
        </div>
      </div>
    </header>

    <nav class="tabs" v-if="!isLogin" aria-label="教务栏目">
      <div class="tabs-inner">
        <RouterLink
          v-for="t in tabs"
          :key="t.to"
          :to="t.to"
          class="tab"
          :class="{ 'is-active': route.path === t.to }"
        >{{ t.label }}</RouterLink>
      </div>
    </nav>

    <main class="page">
      <!-- 原来是裸 <RouterView />，切页是硬切：旧页瞬间消失、新页瞬间出现。
           out-in 让旧页先退新页再进，两页不同时在场（否则高度翻倍也是抖）。 -->
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>

    <footer class="foot" v-if="!isLogin">
      <div class="foot-inner">
        <span>本站为课程项目仿真环境，课表、成绩、借阅数据均为 seed 假数据。</span>
        <span class="code">GET /chat · SSE</span>
      </div>
    </footer>

    <FloatingBall />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 100svh;
}

/* 标识牌：整站唯一的墨蓝面，重量集中在这一条 */
.signplate {
  background: var(--ink);
  color: #e7ebf2;
}

.signplate-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.crest {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1.5px solid rgba(231, 235, 242, 0.45);
  border-radius: 50%;
  font-family: var(--display);
  font-size: 15px;
  color: #fff;
  letter-spacing: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-text strong {
  font-family: var(--display);
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 0.14em;
}

.brand-text em {
  font-style: normal;
  font-size: 11px;
  letter-spacing: 0.1em;
  color: rgba(231, 235, 242, 0.62);
}

.meta {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12.5px;
  color: rgba(231, 235, 242, 0.72);
  flex-wrap: wrap;
}

.meta-sep {
  width: 1px;
  height: 12px;
  background: rgba(231, 235, 242, 0.24);
}

.who {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.who-name {
  color: #fff;
  font-size: 13.5px;
}

.who-id {
  color: rgba(231, 235, 242, 0.62);
}

.logout {
  font: inherit;
  font-size: 12px;
  color: rgba(231, 235, 242, 0.72);
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
}

.logout:hover {
  color: #fff;
}

.tabs {
  background: var(--card);
  border-bottom: 1px solid var(--rule);
}

.tabs-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  gap: 30px;
  overflow-x: auto;
}

.tab {
  position: relative;
  padding: 13px 2px;
  font-size: 14px;
  color: var(--faint);
  white-space: nowrap;
  transition: color 0.16s ease;
}

.tab:hover {
  color: var(--ink);
}

.tab.is-active {
  color: var(--ink);
  font-weight: 600;
}

/* 选中态用朱红细线，全站这点红只留给"当前" */
.tab.is-active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--seal);
}

.page {
  flex: 1;
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  padding: 30px 24px 56px;
}

.foot {
  border-top: 1px solid var(--rule);
  background: var(--card);
}

.foot-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  font-size: 12px;
  color: var(--faint);
  flex-wrap: wrap;
}

@media (max-width: 720px) {
  .signplate-inner,
  .tabs-inner,
  .page,
  .foot-inner {
    padding-inline: 16px;
  }

  .meta {
    display: none;
  }

  .tabs-inner {
    gap: 22px;
  }

  .page {
    padding-top: 22px;
  }
}
</style>
