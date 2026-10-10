<template>
  <div class="profile-container">
    <el-card class="profile-card">
      <template #header>
        <div class="profile-header">
          <span>个人中心</span>
          <el-button text @click="$router.push('/')">返回首页</el-button>
        </div>
      </template>

      <el-descriptions :column="1" border>
        <el-descriptions-item label="用户名">{{ user?.username }}</el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ user?.email }}</el-descriptions-item>
        <el-descriptions-item label="用户 ID">{{ user?.id }}</el-descriptions-item>
      </el-descriptions>

      <el-divider>修改密码</el-divider>
      <el-form :model="passwordForm" label-width="110px" class="password-form">
        <el-form-item label="当前密码">
          <el-input v-model="passwordForm.currentPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="changingPassword" @click="changePassword">
            修改密码
          </el-button>
        </el-form-item>
      </el-form>

      <el-divider>危险操作</el-divider>
      <el-alert
        title="删除账户会永久清理该账户的历史记录、反馈、用量和评估数据。"
        type="warning"
        :closable="false"
      />
      <el-button type="danger" plain class="delete-button" @click="deleteAccount">
        删除账户
      </el-button>
    </el-card>
  </div>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'

export default {
  name: 'Profile',
  data() {
    return {
      user: this.$store.state.auth,
      changingPassword: false,
      passwordForm: {
        currentPassword: '',
        newPassword: '',
        confirmPassword: ''
      }
    }
  },
  methods: {
    async changePassword() {
      const { currentPassword, newPassword, confirmPassword } = this.passwordForm
      if (!currentPassword || newPassword.length < 6) {
        ElMessage.warning('请输入当前密码和至少 6 位的新密码')
        return
      }
      if (newPassword !== confirmPassword) {
        ElMessage.warning('两次输入的新密码不一致')
        return
      }
      this.changingPassword = true
      try {
        await this.$api.changePassword({ currentPassword, newPassword })
        ElMessage.success('密码修改成功，请重新登录')
        this.$store.dispatch('logout')
        this.$router.push('/login')
      } catch (error) {
        // API 拦截器已显示具体错误
      } finally {
        this.changingPassword = false
      }
    },
    async deleteAccount() {
      try {
        await ElMessageBox.confirm(
          '删除后无法恢复，确定要删除账户吗？',
          '确认删除账户',
          { confirmButtonText: '永久删除', cancelButtonText: '取消', type: 'warning' }
        )
        await this.$api.deleteAccount()
        this.$store.dispatch('logout')
        ElMessage.success('账户已删除')
        this.$router.push('/login')
      } catch (error) {
        if (error !== 'cancel' && error !== 'close') {
          ElMessage.error(error.message || '删除账户失败')
        }
      }
    }
  }
}
</script>

<style scoped>
.profile-container {
  max-width: 720px;
  margin: 0 auto;
  padding: 32px 20px;
}

.profile-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.password-form {
  max-width: 560px;
}

.delete-button {
  margin-top: 18px;
}
</style>
