import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: () => import('../views/HomeView.vue') },
    { path: "/academic/schedule", component: () => import('../views/ScheduleView.vue') },
    { path: "/academic/grades", component: () => import('../views/GradesView.vue') },
    { path: "/academic/makeup", component: () => import('../views/MakeupView.vue') },
    { path: "/library", component: () => import('../views/LibraryView.vue') },
  ],
})
