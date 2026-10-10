<template>
  <!-- 统一注入轻提示的全局配置：offset 让提示出现在顶栏之下，max 控制同时堆叠数量 -->
  <el-config-provider :message="messageConfig">
  <div id="app">
    <el-container class="app-container">
      <!-- 登录/注册页自带品牌区与 Tab，不再叠加顶栏 -->
      <el-header v-if="!isAuthPage" class="app-header">
        <div class="header-content">
          <h1 class="app-title">
            <el-icon><Reading /></el-icon>
            CodeMind · AI 代码理解与文档生成助手
          </h1>
          <div class="header-actions">
            <el-button 
              v-if="!$store.state.auth"
              type="text" 
              :class="{ active: $route.path === '/login' }"
              @click="$router.push('/login')">
              <el-icon><User /></el-icon>
              登录
            </el-button>
            <el-button 
              v-if="!$store.state.auth"
              type="text" 
              :class="{ active: $route.path === '/register' }"
              @click="$router.push('/register')">
              <el-icon><EditPen /></el-icon>
              注册
            </el-button>
            <el-button v-if="$store.state.auth" type="text" class="user-info" @click="$router.push('/profile')">
              {{ $store.state.auth.username }}
            </el-button>
            <span v-if="$store.state.auth && quota" class="quota-info">
              今日额度 {{ quota.remaining }}/{{ quota.limit }}
            </span>
            <el-button v-if="$store.state.auth" type="text" @click="logout">
              退出登录
            </el-button>
            <el-button v-if="$store.state.auth" type="text" @click="$router.push('/knowledge')">
              知识库
            </el-button>
            <el-button v-if="$store.state.auth?.role === 'admin'" type="text" @click="$router.push('/admin')">
              管理看板
            </el-button>
            <el-button type="primary" @click="showAboutDialog = true">
              <el-icon><InfoFilled /></el-icon>
              关于系统
            </el-button>
          </div>
        </div>
      </el-header>
      
      <el-main class="app-main" :class="{ 'auth-main': isAuthPage }">
        <router-view />
      </el-main>
    </el-container>

    <!-- 关于对话框 -->
    <el-dialog 
      v-model="showAboutDialog" 
      title="关于系统" 
      width="500px"
      center>
      <div class="about-content">
        <h3>CodeMind</h3>
        <p>基于 LangChain 与 DeepSeek 的代码理解与文档生成系统，结合 RAG 检索增强与结构化输出校验。</p>
        <div class="features">
          <h4>主要功能:</h4>
          <ul>
            <li>多语言支持：JavaScript、Python、Java</li>
            <li>AI 注释生成、代码解释、重构建议</li>
            <li>代码结构分析（AST）</li>
            <li>RAG 知识库检索增强</li>
            <li>语义缓存与真实 Token/成本统计</li>
            <li>历史管理与用户数据隔离</li>
          </ul>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="showAboutDialog = false">确定</el-button>
      </template>
    </el-dialog>
  </div>
  </el-config-provider>
</template>

<script>
import { Reading, InfoFilled, User, EditPen } from '@element-plus/icons-vue'

export default {
  name: 'App',
  components: {
    Reading,
    InfoFilled,
    User,
    EditPen
  },
  data() {
    return {
      showAboutDialog: false,
      quota: null,
      // 轻提示：下移到顶栏之下，最多同时显示 3 条
      messageConfig: { offset: 72, max: 3 }
    }
  },
  computed: {
    // 登录/注册页整页铺满并自带导航，不渲染顶栏
    isAuthPage() {
      return this.$route.path === '/login' || this.$route.path === '/register'
    }
  },
  mounted() {
    window.addEventListener('ai-generation-complete', this.refreshQuota)
    // 登录/注册页右上角「关于系统」入口透出的事件
    window.addEventListener('open-about-dialog', this.openAbout)
    if (this.$store.state.token) {
      this.refreshQuota()
      this.$api.getCurrentUser()
        .then((response) => {
          this.$store.dispatch('refreshAuth', response.user)
        })
        .catch(() => {
          this.$store.dispatch('logout')
        })
    }
  },
  methods: {
    openAbout() {
      this.showAboutDialog = true
    },
    refreshQuota() {
      if (!this.$store.state.token) {
        this.quota = null
        return
      }
      this.$api.getAIQuota().then((response) => {
        this.quota = response.quota
      }).catch(() => {
        this.quota = null
      })
    },
    logout() {
      this.$store.dispatch('logout')
      this.quota = null
      this.$router.push('/login')
    }
  },
  beforeUnmount() {
    window.removeEventListener('ai-generation-complete', this.refreshQuota)
    window.removeEventListener('open-about-dialog', this.openAbout)
  }
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  height: 100vh;
}

.app-container {
  height: 100%;
}

.app-header {
  background: #FFFFFF;
  color: #303133;
  border-bottom: 1px solid #EBEEF5;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.06);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-actions .el-button + .el-button {
  margin-left: 0;
}

/* 登录/注册页需要整页铺满，去掉 el-main 默认内边距 */
.app-main.auth-main {
  padding: 0;
  background: #F5F7FA;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 100%;
  max-width: 1200px;
  margin: 0 auto;
}

.app-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 24px;
  font-weight: 600;
}

.app-main {
  padding: 0;
  background: #F5F7FA;
  overflow: auto;
}

/* 只对文字按钮生效，实心按钮（关于系统）保留白字，
   否则深灰文字会盖在彩色底上，按钮看起来发暗 */
.app-header .header-actions .el-button:not(.el-button--primary):not(.el-button--success):not(.el-button--danger):not(.el-button--warning):not(.el-button--info) {
  color: #606266;
}

.app-header .header-actions .el-button--primary {
  color: #FFFFFF;
}

.user-info {
  color: #303133;
  font-size: 14px;
}

.quota-info {
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
  padding: 4px 10px;
  border: 1px solid #E4E7ED;
  border-radius: 99px;
  background: #F5F7FA;
}

.app-header .header-actions .el-button.active {
  background: rgba(110, 125, 240, 0.12);
  color: #5C6AE0;
}

.app-header .header-actions .el-button:not(.el-button--primary):hover {
  background: rgba(110, 125, 240, 0.08);
  color: #5C6AE0;
}

.about-content {
  text-align: center;
}

.about-content h3 {
  color: #5A6BD0;
  margin-bottom: 15px;
}

.about-content p {
  margin-bottom: 20px;
  line-height: 1.6;
}

.features {
  text-align: left;
}

.features h4 {
  color: #606266;
  margin-bottom: 10px;
}

.features ul {
  list-style: none;
  padding-left: 0;
}

.features li {
  padding: 5px 0;
  color: #909399;
}
</style>