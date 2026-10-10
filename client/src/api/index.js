import axios from 'axios'
import { ElMessage } from 'element-plus'

// 创建axios实例
const api = axios.create({
  baseURL: process.env.VUE_APP_API_BASE_URL || '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
api.interceptors.request.use(
  config => {
    const token = localStorage.getItem('authToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  response => {
    return response.data
  },
  error => {
    if (error.response) {
      if (error.response.status === 401 && localStorage.getItem('authToken')) {
        localStorage.removeItem('authToken')
        localStorage.removeItem('authUser')
        if (window.location.pathname !== '/login') {
          window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
        }
      }
      // 服务器返回错误状态码
      const message = error.response.data?.error?.message || error.response.data?.error || '服务器错误'
      ElMessage.error(message)
    } else if (error.request) {
      // 请求未收到响应
      ElMessage.error('无法连接到服务器，请检查服务是否启动')
    } else {
      // 其他错误
      ElMessage.error('请求配置错误')
    }
    return Promise.reject(error)
  }
)

// API方法
const commentApi = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  getCurrentUser: () => api.get('/auth/me'),
  changePassword: (data) => api.post('/auth/change-password', data),
  deleteAccount: () => api.delete('/auth/me'),
  // 生成注释
  generateComments: (data) => api.post('/generate-comments', data),

  // 基于 LangChain 和大模型生成结构化注释
  generateAIComments: (data) => api.post('/ai/generate-comments', data),

  generateAICommentsStream: async (data, onEvent) => {
    const baseURL = process.env.VUE_APP_API_BASE_URL || '/api'
    const response = await fetch(`${baseURL}/ai/generate-comments/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(localStorage.getItem('authToken')
          ? { Authorization: `Bearer ${localStorage.getItem('authToken')}` }
          : {})
      },
      body: JSON.stringify(data)
    })

    if (!response.ok) {
      let payload = {}
      try {
        payload = await response.json()
      } catch (error) {
        payload = {}
      }
      const requestError = new Error(payload.error?.message || 'AI 服务请求失败')
      requestError.code = payload.error?.code || 'AI_REQUEST_FAILED'
      throw requestError
    }

    if (!response.body) {
      throw new Error('当前浏览器不支持流式响应')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let isDone = false
    while (!isDone) {
      const { value, done } = await reader.read()
      isDone = done
      if (done) continue
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''

      events.forEach((eventText) => {
        const eventName = eventText.match(/^event: (.+)$/m)?.[1]
        const dataLine = eventText.match(/^data: (.+)$/m)?.[1]
        if (eventName && dataLine) {
          onEvent(eventName, JSON.parse(dataLine))
        }
      })
    }
  },

  // 获取后端 AI 配置状态（不返回密钥）
  getAIConfig: () => api.get('/ai/config'),
  getAIQuota: () => api.get('/ai/quota'),
  getAdminMetrics: () => api.get('/admin/metrics'),

  // 管理员：用户管理（列表 / 代建 / 改角色与禁用 / 删除）
  getAdminUsers: () => api.get('/admin/users'),
  createAdminUser: (data) => api.post('/admin/users', data),
  updateAdminUser: (id, data) => api.patch(`/admin/users/${id}`, data),
  deleteAdminUser: (id) => api.delete(`/admin/users/${id}`),

  // 站点是否开放公开注册
  getRegistrationStatus: () => api.get('/auth/registration-status'),

  // 提交 AI 结果反馈
  submitAIFeedback: (data) => api.post('/ai/feedback', data),

  // 查询后端持久化的 AI 生成历史
  getAIHistory: (params) => api.get('/ai/history', { params }),

  // RAG 知识库
  getRagDocuments: () => api.get('/rag/documents'),
  addRagDocument: (data) => api.post('/rag/documents', data),
  getRagDocument: (id) => api.get(`/rag/documents/${id}`),
  deleteRagDocument: (id) => api.delete(`/rag/documents/${id}`),
  searchRag: (data) => api.post('/rag/search', data),
  getRagStats: () => api.get('/rag/stats'),
  seedRag: () => api.post('/rag/seed'),
  
  // 分析代码
  analyzeCode: (data) => api.post('/analyze-code', data),
  
  // 健康检查
  healthCheck: () => api.get('/health')
}

// 安装到Vue实例
export default {
  install(app) {
    app.config.globalProperties.$api = commentApi
    app.provide('$api', commentApi)
  }
}

// 命名导出
export { commentApi }