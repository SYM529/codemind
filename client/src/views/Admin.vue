<template>
  <div class="admin-container">
    <div class="admin-title">
      <div><h2>管理员数据看板</h2><p>监控系统使用量、成本与 AI 质量</p></div>
      <el-button @click="loadMetrics" :loading="loading">刷新数据</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-row :gutter="16" class="metric-row">
      <el-col v-for="item in cards" :key="item.label" :span="6">
        <el-card class="metric-card">
          <div class="metric-label">{{ item.label }}</div>
          <div class="metric-value">{{ item.value }}</div>
        </el-card>
      </el-col>
    </el-row>
    <el-card>
      <template #header>近 7 日调用趋势</template>
      <el-table :data="metrics.daily" stripe>
        <el-table-column prop="date" label="日期" />
        <el-table-column prop="requests" label="调用次数" />
        <el-table-column prop="costUsd" label="估算成本（USD）" />
      </el-table>
    </el-card>

    <el-card class="user-card">
      <template #header>
        <div class="user-card-header">
          <span>用户管理</span>
          <div>
            <el-button size="small" @click="loadUsers" :loading="userLoading">刷新列表</el-button>
            <el-button size="small" type="primary" @click="openCreateDialog">新建账号</el-button>
          </div>
        </div>
      </template>
      <el-alert v-if="userError" :title="userError" type="error" :closable="false" />
      <el-table :data="users" stripe v-loading="userLoading">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="email" label="邮箱" />
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'">{{ row.role === 'admin' ? '管理员' : '普通用户' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.disabled ? 'warning' : 'success'">{{ row.disabled ? '已禁用' : '正常' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="generations" label="生成次数" width="100" />
        <el-table-column label="创建时间" width="120">
          <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="toggleRole(row)" :disabled="isSelf(row)">
              {{ row.role === 'admin' ? '取消管理员' : '设为管理员' }}
            </el-button>
            <el-button size="small" :type="row.disabled ? 'success' : 'warning'" @click="toggleDisabled(row)" :disabled="isSelf(row)">
              {{ row.disabled ? '启用' : '禁用' }}
            </el-button>
            <el-button size="small" type="danger" @click="removeUser(row)" :disabled="isSelf(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新建账号" width="420px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="站点关闭公开注册后，新账号只能由管理员在此创建"
        style="margin-bottom: 16px"
      />
      <el-form :model="form" :rules="formRules" ref="formRef" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="3-20 位字母、数字或下划线" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="name@example.com" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="6-72 位" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate" :loading="submitting">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'

export default {
  name: 'Admin',
  data() {
    return {
      loading: false,
      error: '',
      metrics: { users: 0, usage: {}, feedback: {}, evaluations: {}, daily: [] },
      users: [],
      userLoading: false,
      userError: '',
      dialogVisible: false,
      submitting: false,
      form: { username: '', email: '', password: '', role: 'user' },
      formRules: {
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
          { min: 6, message: '密码长度不能少于 6 位', trigger: 'blur' }
        ]
      }
    }
  },
  computed: {
    cards() {
      const { usage, feedback, evaluations } = this.metrics
      return [
        { label: '用户数量', value: this.metrics.users },
        { label: 'AI 调用次数', value: usage.requests || 0 },
        { label: '估算 Token', value: (usage.inputTokens || 0) + (usage.outputTokens || 0) },
        { label: '估算成本（USD）', value: Number(usage.costUsd || 0).toFixed(4) },
        { label: '反馈有帮助率', value: feedback.helpfulRate == null ? '-' : `${(feedback.helpfulRate * 100).toFixed(1)}%` },
        { label: '函数覆盖率', value: `${((evaluations.functionCoverage || 0) * 100).toFixed(1)}%` },
        { label: '行号有效率', value: `${((evaluations.validLineRate || 0) * 100).toFixed(1)}%` },
        { label: '平均响应时间', value: `${Math.round(evaluations.durationMs || 0)} ms` }
      ]
    },
    currentUserId() {
      const user = JSON.parse(localStorage.getItem('authUser') || 'null')
      return user ? user.id : null
    }
  },
  mounted() {
    this.loadMetrics()
    this.loadUsers()
  },
  methods: {
    // 错误文案统一取后端 {error:{message}}；axios 拦截器已弹提示，这里只做页面内展示
    errorText(error) {
      return error?.response?.data?.error?.message || error?.message || '操作失败'
    },
    async loadMetrics() {
      this.loading = true
      this.error = ''
      try {
        this.metrics = (await this.$api.getAdminMetrics()).metrics
      } catch (error) {
        this.error = this.errorText(error)
        ElMessage.error(this.error)
      } finally {
        this.loading = false
      }
    },
    async loadUsers() {
      this.userLoading = true
      this.userError = ''
      try {
        this.users = (await this.$api.getAdminUsers()).users
      } catch (error) {
        this.userError = this.errorText(error)
      } finally {
        this.userLoading = false
      }
    },
    isSelf(row) {
      return row.id === this.currentUserId
    },
    formatDate(value) {
      return value ? String(value).slice(0, 10) : '-'
    },
    openCreateDialog() {
      this.form = { username: '', email: '', password: '', role: 'user' }
      this.dialogVisible = true
    },
    async submitCreate() {
      try {
        await this.$refs.formRef.validate()
        this.submitting = true
        await this.$api.createAdminUser(this.form)
        ElMessage.success('账号创建成功')
        this.dialogVisible = false
        this.loadUsers()
        this.loadMetrics()
      } catch (error) {
        this.userError = this.errorText(error)
      } finally {
        this.submitting = false
      }
    },
    async toggleDisabled(row) {
      try {
        await this.$api.updateAdminUser(row.id, { disabled: !row.disabled })
        ElMessage.success(row.disabled ? '已启用该账号' : '已禁用该账号')
      } catch (error) {
        this.userError = this.errorText(error)
      }
      this.loadUsers()
    },
    async toggleRole(row) {
      const nextRole = row.role === 'admin' ? 'user' : 'admin'
      try {
        await this.$api.updateAdminUser(row.id, { role: nextRole })
        ElMessage.success(nextRole === 'admin' ? '已设为管理员' : '已取消管理员身份')
      } catch (error) {
        this.userError = this.errorText(error)
      }
      this.loadUsers()
    },
    async removeUser(row) {
      try {
        await ElMessageBox.confirm(
          `删除「${row.username}」会一并清除其生成历史、知识库与缓存数据，且不可恢复。确认删除？`,
          '删除用户',
          { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
        )
      } catch (error) {
        return
      }
      try {
        await this.$api.deleteAdminUser(row.id)
        ElMessage.success('用户及其数据已删除')
        this.loadMetrics()
      } catch (error) {
        this.userError = this.errorText(error)
      }
      this.loadUsers()
    }
  }
}
</script>

<style scoped>
.admin-container { max-width: 1200px; margin: 0 auto; padding: 28px 20px; }
.admin-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.admin-title h2 { margin-bottom: 6px; color: #303133; }
.admin-title p { color: #909399; }
.metric-row { margin-bottom: 16px; }
.metric-card { min-height: 110px; margin-bottom: 16px; }
.metric-label { color: #909399; font-size: 14px; }
.metric-value { color: #303133; font-size: 26px; font-weight: 600; margin-top: 16px; }
.user-card { margin-top: 16px; }
.user-card-header { display: flex; justify-content: space-between; align-items: center; }
</style>
