import { createRouter, createWebHistory } from 'vue-router'

const Home = () => import(/* webpackChunkName: "home" */ '../views/Home.vue')
const History = () => import(/* webpackChunkName: "history" */ '../views/History.vue')
const Login = () => import(/* webpackChunkName: "auth" */ '../views/Login.vue')
const Register = () => import(/* webpackChunkName: "auth" */ '../views/Register.vue')
const Profile = () => import(/* webpackChunkName: "profile" */ '../views/Profile.vue')
const Admin = () => import(/* webpackChunkName: "admin" */ '../views/Admin.vue')
const Knowledge = () => import(/* webpackChunkName: "knowledge" */ '../views/Knowledge.vue')

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home,
    meta: { requiresAuth: true }
  },
  {
    path: '/history',
    name: 'History',
    component: History,
    meta: { requiresAuth: true }
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: Knowledge,
    meta: { requiresAuth: true }
  },
  {
    path: '/login',
    name: 'Login',
    component: Login
  },
  {
    path: '/register',
    name: 'Register',
    component: Register
  },
  {
    path: '/profile',
    name: 'Profile',
    component: Profile,
    meta: { requiresAuth: true }
  },
  {
    path: '/admin',
    name: 'Admin',
    component: Admin,
    meta: { requiresAuth: true, requiresAdmin: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  const isAuthenticated = Boolean(localStorage.getItem('authToken'))
  if (to.meta.requiresAuth && !isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin) {
    const user = JSON.parse(localStorage.getItem('authUser') || 'null')
    if (user?.role !== 'admin') return { name: 'Home' }
  }
  if ((to.name === 'Login' || to.name === 'Register') && isAuthenticated) {
    return { name: 'Home' }
  }
  return true
})

export default router