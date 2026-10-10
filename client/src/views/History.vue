<template>
  <div class="history-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>代码历史记录</span>
          <div class="header-actions">
            <el-select v-model="filterLanguage" placeholder="筛选语言" clearable>
              <el-option label="全部" value="" />
              <el-option label="JavaScript" value="javascript" />
              <el-option label="Python" value="python" />
              <el-option label="Java" value="java" />
            </el-select>
            <el-button type="danger" @click="clearHistory" :disabled="filteredHistory.length === 0">
              <el-icon><DeleteIcon /></el-icon>
              清空历史
            </el-button>
          </div>
        </div>
      </template>

      <div v-if="filteredHistory.length > 0" class="history-content">
        <el-timeline>
          <el-timeline-item
            v-for="item in filteredHistory"
            :key="item.id"
            :timestamp="formatDate(item.timestamp)"
            placement="top"
          >
            <el-card class="history-item">
              <template #header>
                <div class="item-header">
                  <span class="item-title">{{ getLanguageName(item.language) }} 代码</span>
                  <div class="item-actions">
                    <el-button size="small" @click="loadHistoryItem(item)">
                      <el-icon><ViewIcon /></el-icon>
                      加载
                    </el-button>
                    <el-button size="small" type="danger" @click="deleteHistoryItem(item.id)">
                      <el-icon><DeleteIcon /></el-icon>
                      删除
                    </el-button>
                  </div>

                </div>
              </template>

              <div class="item-content">
                <el-descriptions :column="2" size="small">
                  <el-descriptions-item label="函数数量">{{ item.structure?.functions?.length || 0 }}</el-descriptions-item>
                  <el-descriptions-item label="类数量">{{ item.structure?.classes?.length || 0 }}</el-descriptions-item>
                  <el-descriptions-item label="生成注释">{{ item.comments?.length || 0 }} 个</el-descriptions-item>
                  <el-descriptions-item label="代码行数">{{ item.code ? item.code.split('\n').length : 0 }} 行</el-descriptions-item>
                </el-descriptions>

                <!-- 代码预览 -->
                <el-collapse class="code-preview">
                  <el-collapse-item title="代码预览">
                    <pre v-if="item.code" class="code-snippet">{{ truncateCode(item.code) }}</pre>
                  </el-collapse-item>
                  
                  <el-collapse-item v-if="item.comments && item.comments.length > 0" title="注释预览">
                    <div v-for="comment in item.comments.slice(0, 3)" :key="comment.line" class="comment-preview">
                      <strong>第{{ comment.line }}行 - {{ comment.functionName }}</strong>
                      <pre class="comment-snippet">{{ truncateComment(comment.comment) }}</pre>
                    </div>
                    <div v-if="item.comments.length > 3" class="more-comments">
                      还有 {{ item.comments.length - 3 }} 个注释...
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </div>

      <template v-if="aiHistory.length > 0">
        <el-divider content-position="left">AI 生成历史</el-divider>
        <div class="history-content">
          <el-timeline>
            <el-timeline-item
              v-for="item in aiHistory"
              :key="item.generationId"
              :timestamp="formatDate(item.createdAt)"
              placement="top"
            >
              <el-card class="history-item">
                <template #header>
                  <div class="item-header">
                    <span class="item-title">{{ getTaskName(item.task) }} · {{ getLanguageName(item.language) }}</span>
                    <el-button size="small" type="primary" @click="loadAIHistoryItem(item)">
                      <el-icon><ViewIcon /></el-icon>
                      加载
                    </el-button>
                  </div>
                </template>
                <el-descriptions :column="2" size="small">
                  <el-descriptions-item label="模型">{{ item.debug?.model || 'DeepSeek' }}</el-descriptions-item>
                  <el-descriptions-item label="耗时">{{ item.debug?.durationMs || '-' }} ms</el-descriptions-item>
                  <el-descriptions-item label="函数数量">{{ item.comments?.length || 0 }}</el-descriptions-item>
                  <el-descriptions-item label="估算成本">US$ {{ item.debug?.usage?.estimatedCostUsd || 0 }}</el-descriptions-item>
                </el-descriptions>
                <p class="history-summary">{{ item.summary }}</p>
              </el-card>
            </el-timeline-item>
          </el-timeline>
        </div>
      </template>

      <div v-if="filteredHistory.length === 0 && aiHistory.length === 0" class="empty-history">
        <el-empty description="暂无历史记录">
          <el-button type="primary" @click="$router.push('/')">
            开始生成注释
          </el-button>
        </el-empty>
      </div>
    </el-card>
  </div>
</template>

<script>
import { Delete, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

export default {
  name: 'History',
  components: {
    DeleteIcon: Delete,
    ViewIcon: View
  },
  data() {
    return {
      filterLanguage: ''
      ,
      aiHistory: []
    }
  },
  computed: {
    filteredHistory() {
      if (!this.filterLanguage) {
        return this.$store.state.codeHistory
      }
      return this.$store.state.codeHistory.filter(item => 
        item.language === this.filterLanguage
      )
    }
  },
  mounted() {
    this.loadAIHistory()
  },
  methods: {
    async loadAIHistory() {
      try {
        const response = await this.$api.getAIHistory({
          page: 1,
          pageSize: 20,
          language: this.filterLanguage || undefined
        })
        this.aiHistory = response.items || []
      } catch (error) {
        ElMessage.error('读取 AI 历史记录失败')
      }
    },

    getTaskName(task) {
      if (task === '解释代码整体逻辑、主要函数职责和关键数据流') return '代码解释'
      if (task === '识别可维护性问题并给出具体、可执行的重构建议') return '重构建议'
      return '代码注释'
    },

    loadAIHistoryItem(item) {
      this.$store.commit('SET_CURRENT_CODE', item.code)
      this.$store.commit('SET_GENERATED_COMMENTS', item.comments || [])
      this.$store.dispatch('updateSettings', { language: item.language })
      this.$router.push('/')
      ElMessage.success('AI 历史记录已加载到编辑器')
    },

    formatDate(timestamp) {
      return new Date(timestamp).toLocaleString('zh-CN')
    },

    getLanguageName(lang) {
      const names = {
        javascript: 'JavaScript',
        python: 'Python',
        java: 'Java'
      }
      return names[lang] || lang
    },

    truncateCode(code) {
      const lines = code.split('\n')
      if (lines.length <= 10) {
        return code
      }
      return lines.slice(0, 10).join('\n') + '\n...'
    },

    truncateComment(comment) {
      if (comment.length <= 200) {
        return comment
      }
      return comment.substring(0, 200) + '...'
    },

    loadHistoryItem(item) {
      this.$store.commit('SET_CURRENT_CODE', item.code)
      this.$store.commit('SET_GENERATED_COMMENTS', item.comments || [])
      this.$router.push('/')
      
      // 设置语言
      this.$store.dispatch('updateSettings', { language: item.language })
      
      ElMessage.success('历史记录已加载到编辑器')
    },

    async deleteHistoryItem(id) {
      try {
        await ElMessageBox.confirm(
          '确定要删除这条历史记录吗？',
          '提示',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'warning'
          }
        )
        
        const updatedHistory = this.$store.state.codeHistory.filter(item => item.id !== id)
        this.$store.commit('SET_CODE_HISTORY', updatedHistory)
        ElMessage.success('删除成功')
      } catch (error) {
        // 用户取消删除
      }
    },

    async clearHistory() {
      try {
        await ElMessageBox.confirm(
          '确定要清空所有历史记录吗？此操作不可撤销',
          '警告',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'warning'
          }
        )
        
        this.$store.dispatch('clearHistory')
        ElMessage.success('历史记录已清空')
      } catch (error) {
        // 用户取消清空
      }
    }
  }
}
</script>

<style scoped>
.history-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.history-content {
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}

.history-item {
  margin-bottom: 10px;
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.item-title {
  font-weight: bold;
  color: #409EFF;
}

.item-actions {
  display: flex;
  gap: 5px;
}

.item-content {
  margin-top: 10px;
}

.code-preview {
  margin-top: 15px;
}

.code-snippet, .comment-snippet {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  margin: 5px 0;
  line-height: 1.4;
}

.comment-preview {
  margin-bottom: 10px;
  padding: 10px;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
}

.comment-preview strong {
  display: block;
  margin-bottom: 5px;
  color: #606266;
}

.more-comments {
  text-align: center;
  color: #909399;
  font-style: italic;
  margin-top: 10px;
}

.empty-history {
  text-align: center;
  padding: 40px 0;
}

.history-summary {
  margin: 12px 0 0;
  color: #606266;
  line-height: 1.6;
}

:deep(.el-timeline-item__timestamp) {
  color: #909399;
  font-size: 12px;
}
</style>