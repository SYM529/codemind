<template>
  <div class="knowledge-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>RAG 知识库</span>
          <div class="header-actions">
            <el-tag v-if="stats" type="info" effect="plain">
              {{ stats.documents }} 个文档 / {{ stats.chunks }} 个片段 · {{ stats.embeddingMode }}
            </el-tag>
            <el-button type="primary" @click="showAddDialog = true">
              <el-icon><Plus /></el-icon>
              新增文档
            </el-button>
            <el-button @click="seedSamples" :loading="seeding">
              载入示例
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        title="知识库中的内容会在生成 AI 注释时被检索并注入提示词，用于遵循团队规范。"
        type="info"
        :closable="false"
        show-icon
        class="kb-tip"
      />

      <el-divider content-position="left">检索测试</el-divider>
      <div class="search-bar">
        <el-input
          v-model="searchQuery"
          placeholder="输入代码或问题，测试知识库召回效果"
          clearable
          @keyup.enter="runSearch"
        />
        <el-button type="primary" @click="runSearch" :loading="searching">检索</el-button>
      </div>

      <div v-if="searchResults.length > 0" class="search-results">
        <el-card v-for="(item, index) in searchResults" :key="index" class="result-item" shadow="never">
          <div class="result-header">
            <span class="result-title">{{ item.title }} · 第 {{ item.chunkIndex + 1 }} 块</span>
            <el-tag size="small" type="success">相关度 {{ item.score }}</el-tag>
          </div>
          <pre class="result-content">{{ item.content }}</pre>
        </el-card>
      </div>
      <el-empty v-else-if="searched" description="没有检索到相关内容" :image-size="60" />

      <el-divider content-position="left">文档列表</el-divider>
      <el-table :data="documents" style="width: 100%" v-loading="loading">
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column prop="language" label="语言" width="110" />
        <el-table-column prop="chunkCount" label="片段数" width="90" />
        <el-table-column prop="charCount" label="字符数" width="100" />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" @click="viewDocument(row.id)">查看</el-button>
            <el-button size="small" type="danger" @click="removeDocument(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showAddDialog" title="新增知识库文档" width="640px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="例如：团队代码注释规范" />
        </el-form-item>
        <el-form-item label="语言">
          <el-select v-model="form.language">
            <el-option label="文本" value="text" />
            <el-option label="JavaScript" value="javascript" />
            <el-option label="Python" value="python" />
            <el-option label="Java" value="java" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="12"
            placeholder="粘贴规范文档或参考代码"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitDocument">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showViewDialog" title="文档内容" width="720px">
      <template v-if="currentDocument">
        <p class="doc-meta">
          {{ currentDocument.title }} · {{ currentDocument.chunkCount }} 个片段
        </p>
        <pre class="doc-content">{{ currentDocument.content }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

export default {
  name: 'Knowledge',
  components: { Plus },
  data() {
    return {
      documents: [],
      stats: null,
      loading: false,
      saving: false,
      seeding: false,
      searching: false,
      searched: false,
      showAddDialog: false,
      showViewDialog: false,
      currentDocument: null,
      searchQuery: '',
      searchResults: [],
      form: { title: '', language: 'text', content: '' }
    }
  },
  mounted() {
    this.loadDocuments()
    this.loadStats()
  },
  methods: {
    formatDate(timestamp) {
      return new Date(timestamp).toLocaleString('zh-CN')
    },
    async loadDocuments() {
      this.loading = true
      try {
        const response = await this.$api.getRagDocuments()
        this.documents = response.documents || []
      } catch (error) {
        ElMessage.error('读取知识库失败')
      } finally {
        this.loading = false
      }
    },
    async loadStats() {
      try {
        const response = await this.$api.getRagStats()
        this.stats = response.stats
      } catch (error) {
        this.stats = null
      }
    },
    async submitDocument() {
      if (!this.form.title.trim() || !this.form.content.trim()) {
        ElMessage.warning('标题和内容不能为空')
        return
      }
      this.saving = true
      try {
        await this.$api.addRagDocument(this.form)
        ElMessage.success('文档已加入知识库')
        this.showAddDialog = false
        this.form = { title: '', language: 'text', content: '' }
        this.loadDocuments()
        this.loadStats()
      } catch (error) {
        ElMessage.error('保存文档失败')
      } finally {
        this.saving = false
      }
    },
    async seedSamples() {
      this.seeding = true
      try {
        const response = await this.$api.seedRag()
        ElMessage.success(`已载入 ${response.added.length} 篇示例文档`)
        this.loadDocuments()
        this.loadStats()
      } catch (error) {
        ElMessage.error('载入示例失败')
      } finally {
        this.seeding = false
      }
    },
    async runSearch() {
      if (!this.searchQuery.trim()) {
        ElMessage.warning('请输入检索内容')
        return
      }
      this.searching = true
      try {
        const response = await this.$api.searchRag({ query: this.searchQuery, topK: 4 })
        this.searchResults = response.results || []
        this.searched = true
      } catch (error) {
        ElMessage.error('检索失败')
      } finally {
        this.searching = false
      }
    },
    async viewDocument(id) {
      try {
        const response = await this.$api.getRagDocument(id)
        const doc = response.document
        this.currentDocument = {
          title: doc.title,
          chunkCount: doc.chunkCount,
          content: (doc.chunks || []).map((c) => `# 片段 ${c.index + 1}\n${c.content}`).join('\n\n')
        }
        this.showViewDialog = true
      } catch (error) {
        ElMessage.error('读取文档失败')
      }
    },
    async removeDocument(id) {
      try {
        await ElMessageBox.confirm('确定要删除这篇文档吗？', '提示', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning'
        })
        await this.$api.deleteRagDocument(id)
        ElMessage.success('已删除')
        this.loadDocuments()
        this.loadStats()
      } catch (error) {
        // 用户取消
      }
    }
  }
}
</script>

<style scoped>
.knowledge-container {
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

.kb-tip {
  margin-bottom: 10px;
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
  margin-bottom: 10px;
}

.result-item {
  border: 1px solid #e4e7ed;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-title {
  font-weight: bold;
  color: #409eff;
}

.result-content,
.doc-content {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  margin: 0;
  line-height: 1.5;
  max-height: 300px;
  overflow: auto;
}

.doc-meta {
  color: #606266;
  margin-bottom: 10px;
}
</style>
