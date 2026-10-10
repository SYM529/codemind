import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import store from './store'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// 浅色工作台主题：统一品牌主色与圆角，需在 Element Plus 默认样式之后加载
import './assets/theme-light.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import api from './api'

const app = createApp(App)

// 注册Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(store)
app.use(router)
app.use(ElementPlus)
app.use(api)

app.mount('#app')
