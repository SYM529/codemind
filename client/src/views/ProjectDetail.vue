<template>
  <div class="project-detail-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>{{ project ? project.name : '项目详情' }}</span>
          <div class="header-actions">
            <el-tag v-if="project" :type="statusMeta(project.status).type" size="small">
              {{ statusMeta(project.status).text }}
            </el-tag>
            <el-button size="small" @click="$router.push('/projects')">返回项目列表</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="project && project.status === 'failed'"
        :title="`解析失败：${project.errorMessage || '未知原因'}`"
        type="error"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="project && (project.status === 'pending' || project.status === 'indexing')"
        :title="`正在解析：已索引 ${project.indexedFileCount} / ${project.fileCount} 个文件，共 ${project.chunkCount} 个片段`"
        type="warning"
        :closable="false"
        show-icon
      />
      <el-alert
        v-else-if="skipSummary.length"
        :title="`索引完成，已跳过 ${skipSummary.join('、')}`"
        type="info"
        :closable="false"
        show-icon
      />

      <el-descriptions v-if="project" title="项目概览" :column="3" border class="summary">
        <el-descriptions-item label="文件（已索引/总数）">
          {{ project.indexedFileCount }} / {{ project.fileCount }}
        </el-descriptions-item>
        <el-descriptions-item label="知识片段数">{{ project.chunkCount }}</el-descriptions-item>
        <el-descriptions-item label="解压大小">{{ formatSize(project.totalBytes) }}</el-descriptions-item>
        <el-descriptions-item label="压缩包">{{ project.archiveName || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(project.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDate(project.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card v-if="project && project.status === 'ready'" class="search-card">
      <template #header>
        <div class="card-header">
          <span>项目内检索验证</span>
          <el-tag type="success" size="small" effect="plain">仅在「{{ project.name }}」中召回</el-tag>
        </div>
      </template>

      <div class="search-bar">
        <el-input
          v-model="query"
          placeholder="输入函数名、报错信息或问题，验证项目知识库召回效果"
          clearable
          @keyup.enter="runSearch"
        />
        <el-button type="primary" :loading="searching" @click="runSearch">检索</el-button>
      </div>

      <div v-if="results.length" class="search-results">
        <el-card v-for="(item, index) in results" :key="index" class="result-item" shadow="never">
          <div class="result-header">
            <span class="result-title">
              {{ item.relPath || item.title }}
              <template v-if="item.startLine">（L{{ item.startLine }}-{{ item.endLine }}）</template>
              <template v-if="item.symbolName"> · {{ item.symbolName }}</template>
            </span>
            <el-tag size="small" type="success">相关度 {{ item.score }}</el-tag>
          </div>
          <pre class="result-content">{{ item.content }}</pre>
        </el-card>
      </div>
      <el-empty v-else-if="searched" description="没有检索到相关内容" :image-size="60" />
    </el-card>

    <el-card
      v-if="project && (project.status === 'ready' || project.status === 'partial')"
      class="qa-card">
      <template #header>
        <div class="card-header">
          <span>项目问答</span>
          <el-tag type="success" size="small" effect="plain">答案只依据「{{ project.name }}」的代码</el-tag>
        </div>
      </template>

      <div class="qa-input-row">
        <el-input
          v-model="question"
          placeholder="例如：登录流程在哪个函数里实现？"
          clearable
          :disabled="asking"
          @keyup.enter="askQuestion"
        />
        <el-button type="primary" :loading="asking" @click="askQuestion">提问</el-button>
      </div>

      <el-alert
        v-if="qaError"
        :title="qaError"
        type="error"
        :closable="false"
        show-icon
        class="qa-error"
      />

      <div v-if="qaAnswer" class="qa-answer">
        <div class="qa-answer-text">{{ qaAnswer }}</div>
        <div v-if="qaCitations.length" class="qa-citations">
          <div class="qa-citations-title">引用来源</div>
          <div v-for="(item, index) in qaCitations" :key="index" class="qa-citation">
            <span class="qa-citation-index">[{{ index + 1 }}]</span>
            <span class="qa-citation-path">{{ item.relPath }}</span>
            <template v-if="item.startLine">（L{{ item.startLine }}-{{ item.endLine }}）</template>
            <template v-if="item.symbolName"> · {{ item.symbolName }}</template>
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="files-card">
      <template #header>
        <div class="card-header">
          <span>文件清单</span>
          <el-button size="small" @click="loadAll">刷新</el-button>
        </div>
      </template>

      <el-table :data="files" v-loading="loading" style="width: 100%">
        <el-table-column prop="relPath" label="文件路径" min-width="220" />
        <el-table-column prop="language" label="语言" width="110" />
        <el-table-column prop="lineCount" label="行数" width="90" />
        <el-table-column prop="symbolCount" label="符号数" width="90" />
        <el-table-column prop="chunkCount" label="片段数" width="90" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button size="small" @click="viewFile(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && !files.length"
        :description="project && project.status === 'indexing' ? '正在解析文件…' : '暂无索引文件'"
        :image-size="70"
      />
    </el-card>

    <el-dialog v-model="showFileDialog" :title="currentFile ? currentFile.relPath : '文件详情'" width="760px">
      <template v-if="currentFile">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="语言">{{ currentFile.language }}</el-descriptions-item>
          <el-descriptions-item label="行数">{{ currentFile.lineCount }}</el-descriptions-item>
          <el-descriptions-item label="片段数">{{ currentFile.chunkCount }}</el-descriptions-item>
        </el-descriptions>

        <template v-if="currentFile.structure && currentFile.structure.functions.length">
          <el-divider content-position="left">函数</el-divider>
          <el-table :data="currentFile.structure.functions" size="small" max-height="200">
            <el-table-column prop="name" label="函数名" width="180" />
            <el-table-column label="行号" width="120">
              <template #default="{ row }">
                {{ row.endLine ? `${row.line}-${row.endLine}` : row.line }}
              </template>
            </el-table-column>
            <el-table-column label="参数">
              <template #default="{ row }">{{ (row.parameters || []).join(', ') || '无参数' }}</template>
            </el-table-column>
          </el-table>
        </template>

        <template v-if="currentFile.structure && currentFile.structure.classes.length">
          <el-divider content-position="left">类</el-divider>
          <el-table :data="currentFile.structure.classes" size="small">
            <el-table-column prop="name" label="类名" width="180" />
            <el-table-column label="行号">
              <template #default="{ row }">
                {{ row.endLine ? `${row.line}-${row.endLine}` : row.line }}
              </template>
            </el-table-column>
          </el-table>
        </template>

        <el-divider content-position="left">知识片段</el-divider>
        <div v-for="chunk in currentFile.chunks" :key="chunk.index" class="chunk-item">
          <div class="chunk-header">
            <span>片段 {{ chunk.index + 1 }}</span>
            <span class="chunk-meta">
              <template v-if="chunk.symbolName">{{ chunk.symbolName }} · </template>
              L{{ chunk.startLine }}-{{ chunk.endLine }}
            </span>
          </div>
          <pre class="chunk-content">{{ chunk.content }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { ElMessage } from 'element-plus'

const POLL_INTERVAL = 2000
const STATUS_META = {
  pending: { text: '排队中', type: 'info' },
  indexing: { text: '解析中', type: 'warning' },
  ready: { text: '已就绪', type: 'success' },
  partial: { text: '部分完成', type: 'warning' },
  failed: { text: '解析失败', type: 'danger' }
}

export default {
  name: 'ProjectDetail',
  data() {
    return {
      project: null,
      files: [],
      loading: false,
      query: '',
      results: [],
      searched: false,
      searching: false,
      question: '',
      qaAnswer: '',
      qaCitations: [],
      qaError: '',
      asking: false,
      showFileDialog: false,
      currentFile: null,
      pollTimer: null
    }
  },
  computed: {
    projectId() {
      return this.$route.params.projectId
    },
    skipSummary() {
      const detail = this.project && this.project.detail
      if (!detail || !detail.skipped) return []
      const labels = detail.skipReasonLabels || {}
      return Object.entries(detail.skipped)
        .filter(([, count]) => count > 0)
        .map(([reason, count]) => `${labels[reason] || reason} ${count} 个`)
    }
  },
  mounted() {
    this.loadAll()
  },
  beforeUnmount() {
    this.stopPolling()
  },
  methods: {
    statusMeta(status) {
      return STATUS_META[status] || { text: status || '未知', type: 'info' }
    },
    formatDate(timestamp) {
      return timestamp ? new Date(timestamp).toLocaleString('zh-CN') : '-'
    },
    formatSize(bytes) {
      const size = Number(bytes) || 0
      if (size < 1024) return `${size} B`
      if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
      return `${(size / 1024 / 1024).toFixed(2)} MB`
    },
    async loadAll() {
      this.loading = true
      try {
        const [projectResponse, filesResponse] = await Promise.all([
          this.$api.getProject(this.projectId),
          this.$api.getProjectFiles(this.projectId)
        ])
        this.project = projectResponse.project
        this.files = filesResponse.files || []
        this.syncPolling()
      } catch (error) {
        // 响应拦截器已统一提示；项目不存在时退回列表
        if (error.response && error.response.status === 404) {
          this.$router.push('/projects')
        }
      } finally {
        this.loading = false
      }
    },
    syncPolling() {
      const status = this.project && this.project.status
      if (status === 'pending' || status === 'indexing') {
        this.startPolling()
      } else {
        this.stopPolling()
      }
    },
    startPolling() {
      if (this.pollTimer) return
      this.pollTimer = setInterval(this.poll, POLL_INTERVAL)
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
    async poll() {
      try {
        const projectResponse = await this.$api.getProject(this.projectId)
        this.project = projectResponse.project
        if (this.project.status === 'ready' || this.project.status === 'partial') {
          const filesResponse = await this.$api.getProjectFiles(this.projectId)
          this.files = filesResponse.files || []
        }
      } catch (error) {
        this.stopPolling()
        return
      }
      this.syncPolling()
    },
    async runSearch() {
      if (!this.query.trim()) {
        ElMessage.warning('请输入检索内容')
        return
      }
      this.searching = true
      try {
        const response = await this.$api.searchProject(this.projectId, {
          query: this.query.trim(),
          topK: 4
        })
        this.results = response.results || []
        this.searched = true
      } catch (error) {
        // 响应拦截器已统一提示
      } finally {
        this.searching = false
      }
    },
    async askQuestion() {
      if (!this.question.trim()) {
        ElMessage.warning('请输入问题')
        return
      }
      if (this.asking) return

      this.asking = true
      this.qaAnswer = ''
      this.qaCitations = []
      this.qaError = ''
      try {
        await this.$api.askProject(
          this.projectId,
          { question: this.question.trim(), topK: 4 },
          (event, data) => {
            if (event === 'token' && typeof data.token === 'string') {
              this.qaAnswer += data.token
            } else if (event === 'complete') {
              if (data.success) {
                this.qaAnswer = data.answer || ''
                this.qaCitations = data.citations || []
              } else {
                this.qaError = data.message || '问答失败'
              }
            } else if (event === 'error') {
              this.qaError = data.message || 'AI 服务暂时不可用'
            }
          }
        )
      } catch (error) {
        this.qaError = error.message || '问答失败'
      } finally {
        this.asking = false
      }
    },
    async viewFile(documentId) {
      try {
        const response = await this.$api.getProjectFile(this.projectId, documentId)
        this.currentFile = response.file
        this.showFileDialog = true
      } catch (error) {
        // 响应拦截器已统一提示
      }
    }
  }
}
</script>

<style scoped>
.project-detail-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
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

.summary {
  margin-top: 12px;
}

.search-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 15px;
}

.search-results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result-item {
  border: 1px solid #e4e7ed;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
}

.result-title {
  font-weight: bold;
  color: #409eff;
  font-size: 13px;
  word-break: break-all;
}

.qa-input-row {
  display: flex;
  gap: 10px;
}

.qa-error {
  margin-top: 12px;
}

.qa-answer {
  margin-top: 12px;
}

.qa-answer-text {
  white-space: pre-wrap;
  line-height: 1.6;
  color: #303133;
  background: #f0f9ff;
  border: 1px solid #e1f0ff;
  border-radius: 4px;
  padding: 10px 12px;
}

.qa-citations {
  margin-top: 10px;
  font-size: 13px;
}

.qa-citations-title {
  color: #606266;
  font-weight: 600;
  margin-bottom: 6px;
}

.qa-citation {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  color: #606266;
  padding: 3px 0;
}

.qa-citation-index {
  color: #409eff;
  font-weight: 600;
}

.qa-citation-path {
  color: #303133;
  font-family: 'Courier New', monospace;
}

.result-content,
.chunk-content {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  margin: 0;
  line-height: 1.5;
  max-height: 260px;
  overflow: auto;
}

.chunk-item {
  margin-bottom: 10px;
}

.chunk-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}

.chunk-meta {
  color: #909399;
}
</style>
