import { createStore } from 'vuex'

// localStorage 中可能残留损坏数据，读取失败时退回空快照
function readWorkspace() {
  try {
    return JSON.parse(localStorage.getItem('workspace') || 'null')
  } catch (error) {
    return null
  }
}

export default createStore({
  state: {
    // 代码历史记录
    codeHistory: JSON.parse(localStorage.getItem('codeHistory') || '[]'),
    // 用户设置
    settings: {
      autoGenerate: true,
      language: 'javascript',
      commentStyle: 'jsdoc'
    },
    // 当前处理的代码
    currentCode: '',
    // 生成的注释
    generatedComments: []
    ,
    // 首页工作区快照：切走路由或刷新后仍可恢复正在编辑的代码与生成结果
    workspace: readWorkspace(),
    auth: JSON.parse(localStorage.getItem('authUser') || 'null'),
    token: localStorage.getItem('authToken') || ''
  },
  mutations: {
    ADD_CODE_HISTORY(state, historyItem) {
      state.codeHistory.unshift(historyItem)
      // 保持最多50条记录
      if (state.codeHistory.length > 50) {
        state.codeHistory = state.codeHistory.slice(0, 50)
      }
      localStorage.setItem('codeHistory', JSON.stringify(state.codeHistory))
    },
    SET_CODE_HISTORY(state, history) {
      state.codeHistory = history
      localStorage.setItem('codeHistory', JSON.stringify(state.codeHistory))
    },
    UPDATE_SETTINGS(state, settings) {
      state.settings = { ...state.settings, ...settings }
      localStorage.setItem('userSettings', JSON.stringify(state.settings))
    },
    SET_CURRENT_CODE(state, code) {
      state.currentCode = code
    },
    SET_GENERATED_COMMENTS(state, comments) {
      state.generatedComments = comments
    },
    SET_AUTH(state, payload) {
      state.auth = payload.user
      state.token = payload.token
      localStorage.setItem('authUser', JSON.stringify(payload.user))
      localStorage.setItem('authToken', payload.token)
    },
    CLEAR_AUTH(state) {
      state.auth = null
      state.token = ''
      localStorage.removeItem('authUser')
      localStorage.removeItem('authToken')
    },
    CLEAR_HISTORY(state) {
      state.codeHistory = []
      localStorage.removeItem('codeHistory')
    },
    SET_WORKSPACE(state, workspace) {
      state.workspace = workspace
      try {
        localStorage.setItem('workspace', JSON.stringify(workspace))
      } catch (error) {
        // 超出存储配额时只保留内存态，不影响当前会话
      }
    },
    CLEAR_WORKSPACE(state) {
      state.workspace = null
      localStorage.removeItem('workspace')
    }
  },
  actions: {
    saveCodeHistory({ commit }, historyItem) {
      commit('ADD_CODE_HISTORY', {
        ...historyItem,
        timestamp: new Date().toISOString(),
        id: Date.now().toString()
      })
    },
    updateSettings({ commit }, settings) {
      commit('UPDATE_SETTINGS', settings)
    },
    setAuth({ commit }, payload) {
      commit('SET_AUTH', payload)
    },
    refreshAuth({ commit }, user) {
      commit('SET_AUTH', { user, token: localStorage.getItem('authToken') || '' })
    },
    logout({ commit }) {
      commit('CLEAR_AUTH')
    },
    clearHistory({ commit }) {
      commit('CLEAR_HISTORY')
    }
  },
  getters: {
    getRecentHistory: (state) => (limit = 10) => {
      return state.codeHistory.slice(0, limit)
    },
    getHistoryByLanguage: (state) => (language) => {
      return state.codeHistory.filter(item => item.language === language)
    }
  }
})