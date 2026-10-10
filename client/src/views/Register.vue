<template>
  <AuthShell active="register" :register-enabled="registrationOpen">
    <h3 class="auth-heading">创建账号</h3>
    <p class="auth-sub">填写以下信息完成注册</p>

    <el-alert
      v-if="registrationClosed"
      type="warning"
      show-icon
      :closable="false"
      title="该站点已关闭公开注册"
      description="请联系管理员为你创建账号，或返回登录页。"
    />

    <el-form
      :model="registerForm"
      :rules="registerRules"
      ref="registerFormRef">
      <el-form-item prop="username">
        <el-input
          v-model="registerForm.username"
          placeholder="请输入用户名"
          prefix-icon="User"
        />
      </el-form-item>

      <el-form-item prop="email">
        <el-input
          v-model="registerForm.email"
          placeholder="请输入邮箱"
          prefix-icon="Message"
        />
      </el-form-item>

      <el-form-item prop="password">
        <el-input
          v-model="registerForm.password"
          :type="passwordVisible ? 'text' : 'password'"
          placeholder="请输入密码"
          prefix-icon="Lock">
          <template #suffix>
            <span class="pwd-toggle" :title="passwordVisible ? '隐藏密码' : '显示密码'" @click="passwordVisible = !passwordVisible">
              <View v-if="!passwordVisible" />
              <Hide v-else />
            </span>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item prop="confirmPassword">
        <el-input
          v-model="registerForm.confirmPassword"
          :type="confirmVisible ? 'text' : 'password'"
          placeholder="请确认密码"
          prefix-icon="Lock"
          @keyup.enter="handleRegister">
          <template #suffix>
            <span class="pwd-toggle" :title="confirmVisible ? '隐藏密码' : '显示密码'" @click="confirmVisible = !confirmVisible">
              <View v-if="!confirmVisible" />
              <Hide v-else />
            </span>
          </template>
        </el-input>
      </el-form-item>

      <button
        type="button"
        class="auth-submit"
        :disabled="loading || registrationClosed"
        @click="handleRegister">
        {{ loading ? '注册中…' : '注册' }}
      </button>
    </el-form>

    <div class="auth-tip">
      已有账号？<span class="link" @click="$router.push('/login')">立即登录</span>
    </div>
  </AuthShell>
</template>

<script>
import AuthShell from '../components/AuthShell.vue'

export default {
  name: 'Register',
  components: { AuthShell },
  data() {
    const validateConfirmPassword = (rule, value, callback) => {
      if (value !== this.registerForm.password) {
        callback(new Error('两次输入的密码不一致'))
      } else {
        callback()
      }
    }

    return {
      registerForm: {
        username: '',
        email: '',
        password: '',
        confirmPassword: ''
      },
      loading: false,
      registrationClosed: false,
      passwordVisible: false,
      confirmVisible: false,
      registerRules: {
        username: [
          { required: true, message: '请输入用户名', trigger: 'blur' },
          { min: 3, max: 20, message: '用户名长度在 3 到 20 个字符', trigger: 'blur' }
        ],
        email: [
          { required: true, message: '请输入邮箱地址', trigger: 'blur' },
          { type: 'email', message: '请输入正确的邮箱地址', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请输入密码', trigger: 'blur' },
          { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
        ],
        confirmPassword: [
          { required: true, message: '请确认密码', trigger: 'blur' },
          { validator: validateConfirmPassword, trigger: 'blur' }
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
        this.registrationClosed = (await this.$api.getRegistrationStatus()).registrationOpen === false
      } catch (error) {
        this.registrationClosed = false
      }
    },
    async handleRegister() {
      if (this.registrationClosed) {
        this.$message.error('该站点已关闭公开注册')
        return
      }
      try {
        await this.$refs.registerFormRef.validate()
        this.loading = true

        await this.$api.register({
          username: this.registerForm.username,
          email: this.registerForm.email,
          password: this.registerForm.password
        })
        this.$message.success('注册成功，请登录')
        this.$router.push('/login')
        this.loading = false
      } catch (error) {
        this.loading = false
      }
    }
  }
}
</script>
