import { createRouter, createWebHistory } from 'vue-router'
import ReelsView from './views/ReelsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'reels', component: ReelsView },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('./views/DashboardView.vue'),
    },
  ],
})

export default router
