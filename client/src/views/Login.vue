<template>
  <AuthShell active="login" :register-enabled="registrationOpen">
    <h3 class="auth-heading">欢迎回来</h3>
    <p class="auth-sub">请输入您的账号信息</p>

    <el-form :model="loginForm" :rules="loginRules" ref="loginFormRef">
      <el-form-item prop="username">
        <el-input
          v-model="loginForm.username"
          placeholder="请输入用户名"
          prefix-icon="User"
        />
      </el-form-item>

      <el-form-item prop="password">
        <el-input
          v-model="loginForm.password"
          :type="passwordVisible ? 'text' : 'password'"
          placeholder="请输入密码"
          prefix-icon="Lock"
          @keyup.enter="handleLogin">
          <template #suffix>
            <span class="pwd-toggle" :title="passwordVisible ? '隐藏密码' : '显示密码'" @click="passwordVisible = !passwordVisible">
              <View v-if="!passwordVisible" />
              <Hide v-else />
            </span>
          </template>
        </el-input>
      </el-form-item>

      <button type="button" class="auth-submit" :disabled="loading" @click="handleLogin">
        {{ loading ? '登录中…' : '登录' }}
      </button>
    </el-form>

    <div v-if="registrationOpen" class="auth-tip">
      还没有账号？<span class="link" @click="$router.push('/register')">立即注册</span>
    </div>
  </AuthShell>
</template>

<script>
import AuthShell from '../components/AuthShell.vue'

export default {
  name: 'Login',
  components: { AuthShell },
  data() {
    return {
      loginForm: {
        username: '',
        password: ''
      },
      loading: false,
      registrationOpen: true,
      passwordVisible: false,
      loginRules: {
        username: [
          { required: true, message: '请输入用户名', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请输入密码', trigger: 'blur' },
          { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
        ]
      }
    }
  },
  mounted() {
    this.loadRegistrationStatus()
  },
  methods: {
    async loadRegistrationStatus() {
      try {
        this.registrationOpen = (await this.$api.getRegistrationStatus()).registrationOpen !== false
      } catch (error) {
        this.registrationOpen = true
      }
    },
    async handleLogin() {
      try {
        await this.$refs.loginFormRef.validate()
        this.loading = true

        const response = await this.$api.login(this.loginForm)
        this.$store.dispatch('setAuth', response)
        this.$message.success('登录成功')
        this.$router.push(this.$route.query.redirect || '/')
        this.loading = false
      } catch (error) {
        this.loading = false
      }
    }
  }
}
</script>
