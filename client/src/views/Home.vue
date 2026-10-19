<template>
  <div class="home-container">
    <el-row :gutter="20" class="main-row">
      <!-- 左侧代码输入区域 -->
      <el-col :span="12">
        <el-card class="code-input-card">
          <template #header>
            <div class="card-header">
              <span>代码输入</span>
              <div class="header-actions">
                <div class="select-group">
                  <el-select v-model="currentLanguage" placeholder="选择语言" @change="onLanguageChange">
                    <el-option label="JavaScript" value="javascript" />
                    <el-option label="Python" value="python" />
                    <el-option label="Java" value="java" />
                  </el-select>
                  <el-select v-model="commentStyle" placeholder="注释风格">
                    <el-option label="JSDoc / JavaDoc" value="jsdoc" />
                    <el-option label="Python Docstring" value="docstring" />
                    <el-option label="简洁说明" value="default" />
                  </el-select>
                  <el-select v-model="aiTask" placeholder="AI 任务">
                    <el-option label="生成代码注释" value="comment" />
                    <el-option label="解释代码逻辑" value="explain" />
                    <el-option label="重构建议" value="refactor" />
                  </el-select>
                </div>
                <div class="button-group">
                  <el-button type="primary" @click="analyzeCode" :loading="analyzing">
                    <el-icon><Search /></el-icon>
                    分析代码
                  </el-button>
                  <el-button type="success" @click="generateComments" :loading="generating">
                    <el-icon><MagicStick /></el-icon>
                    {{ aiTaskLabel }}
                  </el-button>
                  <el-button class="history-button" @click="$router.push('/history')">
                    <el-icon><Clock /></el-icon>
                    查看历史
                  </el-button>
                </div>
              </div>
            </div>
          </template>
          
          <div class="code-editor-container">
            <el-input
              v-model="codeInput"
              type="textarea"
              :rows="20"
              placeholder="请输入代码..."
              resize="none"
              class="code-textarea"
            />
          </div>
          
          <div class="input-footer">
            <el-button text @click="loadExample">加载示例代码</el-button>
            <el-button text @click="clearCode">清空</el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧结果区域 -->
      <el-col :span="12">
        <el-tabs v-model="activeTab" type="border-card" class="result-tabs">
          <!-- 代码结构分析 -->
          <el-tab-pane label="结构分析" name="structure">
            <div v-if="codeStructure" class="structure-content">
              <el-descriptions title="代码结构概览" :column="2" border>
                <el-descriptions-item label="总行数">{{ codeStructure.totalLines }}</el-descriptions-item>
                <el-descriptions-item label="函数数量">{{ codeStructure.functions.length }}</el-descriptions-item>
                <el-descriptions-item label="类数量">{{ codeStructure.classes.length }}</el-descriptions-item>
                <el-descriptions-item label="变量数量">{{ codeStructure.variables.length }}</el-descriptions-item>
              </el-descriptions>

              <!-- 函数列表 -->
              <el-card v-if="codeStructure.functions.length > 0" class="section-card">
                <template #header>
                  <span>函数列表</span>
                </template>
                <el-table :data="codeStructure.functions" size="small">
                  <el-table-column prop="name" label="函数名" width="150" />
                  <el-table-column prop="line" label="行号" width="80" />
                  <el-table-column prop="parameters" label="参数">
                    <template #default="{ row }">
                      {{ row.parameters.join(', ') || '无参数' }}
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>

              <!-- 类列表 -->
              <el-card v-if="codeStructure.classes.length > 0" class="section-card">
                <template #header>
                  <span>类列表</span>
                </template>
                <el-table :data="codeStructure.classes" size="small">
                  <el-table-column prop="name" label="类名" />
                  <el-table-column prop="line" label="行号" width="80" />
                </el-table>
              </el-card>
            </div>
            <div v-else class="empty-state">
              <el-empty description="请先输入代码并进行分析" />
            </div>
          </el-tab-pane>

          <!-- 注释预览 -->
          <el-tab-pane label="AI 注释预览" name="comments">
            <div v-if="generatedComments.length > 0 || aiSummary || aiRisks.length > 0 || aiSuggestions.length > 0" class="comments-content">
              <el-alert
                v-if="aiSummary"
                :title="aiSummary"
                type="success"
                :closable="false"
                show-icon
                class="ai-summary"
              />
              <el-card v-for="comment in generatedComments" :key="comment.line" class="comment-card">
                <template #header>
                  <span>函数: {{ comment.functionName }} (第{{ comment.line }}行)</span>
                </template>
                <pre class="comment-pre">{{ comment.comment }}</pre>
                <div class="comment-actions">
                  <el-button size="small" @click="copyComment(comment.comment)">
                    <el-icon><DocumentCopy /></el-icon>
                    复制
                  </el-button>
                </div>
              </el-card>
              <el-card v-if="aiSuggestions.length > 0 || aiRisks.length > 0" class="ai-insights-card">
                <template #header>
                  <span>AI 分析建议</span>
                </template>
                <el-alert
                  v-for="risk in aiRisks"
                  :key="`risk-${risk}`"
                  :title="risk"
                  type="warning"
                  :closable="false"
                  class="insight-item"
                />
                <el-alert
                  v-for="suggestion in aiSuggestions"
                  :key="`suggestion-${suggestion}`"
                  :title="suggestion"
                  type="info"
                  :closable="false"
                  class="insight-item"
                />
              </el-card>
              <el-card class="feedback-card">
                <template #header>
                  <span>生成结果反馈</span>
                </template>
                <div v-if="feedbackSubmitted" class="feedback-submitted">
                  感谢反馈，当前 AI 结果质量指标：{{ feedbackMetrics.helpfulRate === null ? '暂无数据' : `${(feedbackMetrics.helpfulRate * 100).toFixed(1)}% 有帮助` }}
                </div>
                <div v-else class="feedback-actions">
                  <span>这次生成结果对你有帮助吗？</span>
                  <el-button size="small" type="success" @click="submitFeedback('helpful')">有帮助</el-button>
                  <el-button size="small" @click="submitFeedback('needs_improvement')">需要改进</el-button>
                </div>
              </el-card>
            </div>
            <div v-else class="empty-state">
              <el-empty description="请先生成注释" />
            </div>
          </el-tab-pane>

          <!-- 完整代码预览 -->
          <el-tab-pane label="AI 调试信息" name="debug">
            <DebugPanel :debug="aiDebug" :config="aiConfig" :formatted-result="formattedAIResult" />
          </el-tab-pane>

          <el-tab-pane label="完整预览" name="preview">
            <div v-if="codeInput && generatedComments.length > 0" class="preview-content">
              <el-alert
                title="带注释的完整代码"
                type="info"
                :closable="false"
                show-icon
              />
              <pre class="full-code-pre">{{ getAnnotatedCode }}</pre>
              <div class="preview-actions">
                <el-button type="primary" @click="copyFullCode">
                  <el-icon><DocumentCopy /></el-icon>
                  复制完整代码
                </el-button>
                <el-button @click="saveToHistory">
                  <el-icon><FolderOpened /></el-icon>
                  保存到历史
                </el-button>
              </div>
            </div>
            <div v-else class="empty-state">
              <el-empty description="请先生成注释以查看完整预览" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-col>
    </el-row>
  </div>
</template>

<script>
import { Search, MagicStick, DocumentCopy, FolderOpened, Clock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import DebugPanel from '../components/DebugPanel.vue'
import { copyText } from '../utils/clipboard'

// 各语言的推荐注释风格，切换语言时自动带出，用户仍可手动改
const RECOMMENDED_COMMENT_STYLE = {
  javascript: 'jsdoc',
  java: 'jsdoc',
  python: 'docstring'
}

export default {
  name: 'Home',
  components: {
    Search,
    MagicStick,
    DocumentCopy,
    FolderOpened,
    Clock,
    DebugPanel
  },
  data() {
    return {
      codeInput: '',
      currentLanguage: 'javascript',
      activeTab: 'structure',
      analyzing: false,
      generating: false,
      codeStructure: null,
      generatedComments: [],
      aiSummary: '',
      aiRisks: [],
      aiSuggestions: [],
      aiDebug: null,
      generationId: '',
      feedbackSubmitted: false,
      feedbackMetrics: {
        helpfulRate: null
      },
      aiConfig: {
        configured: false,
        model: '未加载',
        framework: 'LangChain.js'
      },
      commentStyle: 'jsdoc'
      ,
      aiTask: 'comment'
    }
  },
  computed: {
    aiTaskLabel() {
      return {
        comment: '生成注释',
        explain: '解释代码',
        refactor: '生成重构建议'
      }[this.aiTask]
    },

    aiTaskPrompt() {
      return {
        comment: '生成函数级代码注释',
        explain: '解释代码整体逻辑、主要函数职责和关键数据流',
        refactor: '识别可维护性问题并给出具体、可执行的重构建议'
      }[this.aiTask]
    },

    formattedAIResult() {
      return JSON.stringify({
        summary: this.aiSummary,
        comments: this.generatedComments,
        risks: this.aiRisks,
        suggestions: this.aiSuggestions
      }, null, 2)
    },

    getAnnotatedCode() {
      if (!this.codeInput || this.generatedComments.length === 0) return ''
      
      const lines = this.codeInput.split('\n')
      const commentsMap = {}
      
      this.generatedComments.forEach(comment => {
        commentsMap[comment.line] = comment.comment
      })
      
      let result = []
      for (let i = 0; i < lines.length; i++) {
        const lineNumber = i + 1
        if (commentsMap[lineNumber]) {
          result.push(commentsMap[lineNumber])
        }
        result.push(lines[i])
      }
      
      return result.join('\n')
    },

    workspaceSnapshot() {
      return {
        codeInput: this.codeInput,
        currentLanguage: this.currentLanguage,
        activeTab: this.activeTab,
        codeStructure: this.codeStructure,
        generatedComments: this.generatedComments,
        aiSummary: this.aiSummary,
        aiRisks: this.aiRisks,
        aiSuggestions: this.aiSuggestions,
        aiDebug: this.aiDebug,
        generationId: this.generationId,
        feedbackSubmitted: this.feedbackSubmitted,
        feedbackMetrics: this.feedbackMetrics,
        commentStyle: this.commentStyle,
        aiTask: this.aiTask
      }
    }
  },
  watch: {
    // 编辑或生成后自动保存工作区，切走路由再回来不会丢
    workspaceSnapshot: {
      handler(value) {
        clearTimeout(this._workspaceTimer)
        this._workspaceTimer = setTimeout(() => {
          this.$store.commit('SET_WORKSPACE', value)
        }, 300)
      },
      deep: true
    }
  },
  beforeUnmount() {
    // 防抖定时器可能还没触发就切走，离开前立即保存一次
    clearTimeout(this._workspaceTimer)
    this.$store.commit('SET_WORKSPACE', this.workspaceSnapshot)
  },
  methods: {
    restoreWorkspace() {
      // 从历史记录点「加载」进来时优先用它，且只消费一次，避免与工作区快照互相覆盖
      if (this.$store.state.currentCode) {
        this.codeInput = this.$store.state.currentCode
        this.generatedComments = this.$store.state.generatedComments || []
        this.$store.commit('SET_CURRENT_CODE', '')
        this.$store.commit('SET_GENERATED_COMMENTS', [])
        this.activeTab = this.generatedComments.length > 0 ? 'comments' : 'structure'
        return
      }

      const saved = this.$store.state.workspace
      if (!saved) return
      this.codeInput = saved.codeInput || ''
      this.currentLanguage = saved.currentLanguage || this.currentLanguage
      this.activeTab = saved.activeTab || 'structure'
      this.codeStructure = saved.codeStructure || null
      this.generatedComments = saved.generatedComments || []
      this.aiSummary = saved.aiSummary || ''
      this.aiRisks = saved.aiRisks || []
      this.aiSuggestions = saved.aiSuggestions || []
      this.aiDebug = saved.aiDebug || null
      this.generationId = saved.generationId || ''
      this.feedbackSubmitted = Boolean(saved.feedbackSubmitted)
      this.feedbackMetrics = saved.feedbackMetrics || { helpfulRate: null }
      this.commentStyle = saved.commentStyle || 'jsdoc'
      this.aiTask = saved.aiTask || 'comment'
    },

    async analyzeCode() {
      if (!this.codeInput.trim()) {
        ElMessage.warning('请输入代码内容')
        return
      }

      this.analyzing = true
      try {
        const response = await this.$api.analyzeCode({
          code: this.codeInput,
          language: this.currentLanguage
        })
        
        if (response.success) {
          this.codeStructure = response.structure
          this.codeStructure.totalLines = response.totalLines
          ElMessage.success('代码分析完成')
          this.activeTab = 'structure'
        }
      } catch (error) {
        ElMessage.error('分析代码时发生错误')
        console.error('分析错误:', error)
      } finally {
        this.analyzing = false
      }
    },

    async generateComments() {
      if (!this.codeInput.trim()) {
        ElMessage.warning('请输入代码内容')
        return
      }
      if (this.codeInput.length > 20000) {
        ElMessage.warning('代码长度不能超过 20000 个字符')
        return
      }

      this.generating = true
      this.aiSummary = 'AI 正在分析代码，请稍候...'
      this.aiDebug = null
      try {
        let response
        await this.$api.generateAICommentsStream({
          code: this.codeInput,
          language: this.currentLanguage,
          style: this.commentStyle,
          task: this.aiTaskPrompt
        }, (event, data) => {
          if (event === 'token') {
            this.aiSummary = 'AI 正在生成结构化结果...'
          }
          if (event === 'error') {
            const streamError = new Error(data.message || 'AI 服务暂时不可用，请稍后重试')
            streamError.code = data.code
            throw streamError
          }
          if (event === 'complete') {
            response = data
          }
        })
        
        if (response?.success) {
          this.codeStructure = response.structure
          this.codeStructure.totalLines = this.codeInput.split('\n').length
          this.generatedComments = response.comments
          this.aiSummary = response.summary
          this.aiRisks = response.risks || []
          this.aiSuggestions = response.suggestions || []
          this.aiDebug = response.debug || null
          this.generationId = response.generationId || ''
          this.feedbackSubmitted = false
          this.feedbackMetrics = { helpfulRate: null }
          ElMessage.success(this.aiTask === 'comment'
            ? `AI 成功生成 ${response.comments.length} 个注释`
            : 'AI 分析完成')
          this.activeTab = 'comments'
          window.dispatchEvent(new Event('ai-generation-complete'))
        }
      } catch (error) {
        ElMessage.error(error.message || '生成注释时发生错误')
        console.error('生成错误:', error)
      } finally {
        if (!this.generatedComments.length) {
          this.aiSummary = ''
        }
        this.generating = false
      }
    },

    onLanguageChange() {
      // 注释风格跟随语言给出推荐值（Python → Docstring，其余 → JSDoc/JavaDoc）
      this.commentStyle = RECOMMENDED_COMMENT_STYLE[this.currentLanguage] || 'jsdoc'
      this.codeStructure = null
      this.generatedComments = []
      this.aiSummary = ''
      this.aiRisks = []
      this.aiSuggestions = []
      this.aiDebug = null
      this.generationId = ''
      this.feedbackSubmitted = false
    },

    loadExample() {
      const examples = {
        javascript: `function calculateSum(a, b) {
    return a + b;
}

const multiplyNumbers = (x, y) => {
    return x * y;
}

class Calculator {
    constructor() {
        this.result = 0;
    }
    
    add(value) {
        this.result += value;
        return this.result;
    }
}`,
        python: `def calculate_sum(a, b):
    return a + b

def multiply_numbers(x, y):
    return x * y

class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, value):
        self.result += value
        return self.result`,
        java: `public class Calculator {
    private int result;
    
    public Calculator() {
        this.result = 0;
    }
    
    public int calculateSum(int a, int b) {
        return a + b;
    }
    
    public int multiplyNumbers(int x, int y) {
        return x * y;
    }
    
    public void add(int value) {
        this.result += value;
    }
}`
      }
      
      this.codeInput = examples[this.currentLanguage]
      ElMessage.info('示例代码已加载')
    },

    clearCode() {
      this.codeInput = ''
      this.codeStructure = null
      this.generatedComments = []
      this.aiSummary = ''
      this.aiRisks = []
      this.aiSuggestions = []
      this.aiDebug = null
      this.generationId = ''
      this.feedbackSubmitted = false
      ElMessage.info('代码已清空')
    },

    async copyComment(comment) {
      try {
        await copyText(comment)
        ElMessage.success('注释已复制到剪贴板')
      } catch (error) {
        ElMessage.error('复制失败')
      }
    },

    async copyFullCode() {
      try {
        await copyText(this.getAnnotatedCode)
        ElMessage.success('完整代码已复制到剪贴板')
      } catch (error) {
        ElMessage.error('复制失败')
      }
    },

    async submitFeedback(rating) {
      if (!this.generationId) {
        ElMessage.warning('当前结果缺少生成标识，无法提交反馈')
        return
      }

      try {
        const response = await this.$api.submitAIFeedback({
          generationId: this.generationId,
          rating
        })
        this.feedbackSubmitted = true
        this.feedbackMetrics = response.metrics
        ElMessage.success('感谢你的反馈')
      } catch (error) {
        ElMessage.error('反馈提交失败')
      }
    },

    saveToHistory() {
      this.$store.dispatch('saveCodeHistory', {
        code: this.codeInput,
        language: this.currentLanguage,
        comments: this.generatedComments,
        structure: this.codeStructure
      })
      ElMessage.success('已保存到历史记录')
    }
  },
  mounted() {
    this.$api.getAIConfig().then((config) => {
      this.aiConfig = config
    })

    // 加载用户设置
    const savedSettings = localStorage.getItem('userSettings')
    if (savedSettings) {
      const settings = JSON.parse(savedSettings)
      this.currentLanguage = settings.language
    }

    this.restoreWorkspace()
  }
}
</script>

<style scoped>
.home-container {
  padding: 20px;
  height: calc(100vh - 60px);
}

.main-row {
  height: 100%;
}

.code-input-card, .result-tabs {
  height: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.header-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: stretch;
  width: 100%;
  margin-top: 8px;
}

.select-group,
.button-group {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
}

.select-group {
  flex-wrap: nowrap;
}

.button-group {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.select-group :deep(.el-select) {
  flex: 1 1 0;
  min-width: 0;
  width: 0;
}

.button-group :deep(.el-button) {
  margin-left: 0;
}

.header-actions :deep(.el-select .el-input__wrapper) {
  background-color: #fff;
}

.header-actions :deep(.el-select .el-input__inner),
.header-actions :deep(.el-select .el-input__inner:hover),
.header-actions :deep(.el-select .el-input__inner:focus) {
  color: #606266 !important;
  -webkit-text-fill-color: #606266;
  caret-color: #606266;
}

.header-actions :deep(.el-select .el-input__inner::placeholder) {
  color: #a8abb2 !important;
  -webkit-text-fill-color: #a8abb2;
}

.header-actions :deep(.el-select .el-input__suffix) {
  color: #909399;
}

/* 排除实心按钮：否则深灰文字会盖在彩色底上，按钮看起来发暗 */
.header-actions :deep(.el-button:not(.is-loading):not(.el-button--primary):not(.el-button--success)) {
  color: #606266;
}

.header-actions :deep(.history-button) {
  color: #6E7DF0 !important;
  border-color: #A2ACF7;
  background-color: #fff;
  -webkit-text-fill-color: #6E7DF0;
  flex-shrink: 0;
  min-width: 104px;
}

.header-actions :deep(.history-button:hover),
.header-actions :deep(.history-button:focus) {
  color: #fff !important;
  border-color: #6E7DF0;
  background-color: #6E7DF0;
  -webkit-text-fill-color: #fff;
}

.header-actions :deep(.el-button--primary),
.header-actions :deep(.el-button--success) {
  color: #fff;
}

@media (max-width: 900px) {
  .select-group {
    flex-wrap: wrap;
  }

  .select-group :deep(.el-select) {
    flex: 1 1 140px;
    width: auto;
  }
}

.code-editor-container {
  margin-bottom: 15px;
}

.code-textarea {
  font-family: 'Courier New', monospace;
  font-size: 14px;
}

.input-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.structure-content, .comments-content, .preview-content {
  height: 500px;
  overflow-y: auto;
}

.section-card {
  margin-top: 15px;
}

.comment-card {
  margin-bottom: 10px;
}

.ai-summary {
  margin-bottom: 12px;
}

.ai-insights-card {
  margin-bottom: 12px;
}

.feedback-card {
  margin-bottom: 12px;
}

.feedback-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.feedback-submitted {
  color: #67c23a;
}

.insight-item {
  margin-bottom: 8px;
}

.comment-pre {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  margin: 0;
}

.comment-actions {
  margin-top: 10px;
}

.full-code-pre {
  background: #f5f7fa;
  padding: 15px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  margin: 15px 0;
  line-height: 1.4;
}

.preview-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
}

.empty-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>