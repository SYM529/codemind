<template>
  <div class="project-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>项目知识库</span>
          <div class="header-actions">
            <el-tag v-if="projects.length" type="info" effect="plain">
              {{ projects.length }} 个项目 / {{ totalChunks }} 个片段
            </el-tag>
            <el-button type="primary" @click="showUploadDialog = true">
              <el-icon><Upload /></el-icon>
              上传项目 ZIP
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        title="上传整个项目的 ZIP 压缩包，系统会扫描代码文件、解析结构并建立项目知识库。每个项目的知识库互相隔离，检索时不会串项目。"
        type="info"
        :closable="false"
        show-icon
        class="project-tip"
      />

      <el-table :data="projects" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="项目名称" min-width="160" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" size="small">
              {{ statusMeta(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="文件（已索引/总数）" width="160">
          <template #default="{ row }">
            {{ row.indexedFileCount }} / {{ row.fileCount }}
          </template>
        </el-table-column>
        <el-table-column prop="chunkCount" label="片段数" width="90" />
        <el-table-column label="解压大小" width="110">
          <template #default="{ row }">{{ formatSize(row.totalBytes) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row.projectId)">详情</el-button>
            <el-button size="small" type="danger" @click="removeProject(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && !projects.length"
        description="还没有项目，先上传一个 ZIP 压缩包"
        :image-size="70"
      />
    </el-card>

    <el-dialog v-model="showUploadDialog" title="上传项目 ZIP" width="600px" @closed="resetUpload">
      <el-alert
        title="仅索引源码与文档：.py / .js / .mjs / .jsx / .ts / .tsx / .java / .md / .txt / .rst。会自动忽略 node_modules、.git、dist、venv 等目录，密钥与环境变量文件不会被读取。"
        type="warning"
        :closable="false"
        show-icon
        class="upload-tip"
      />

      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        :on-change="onFileChange"
        accept=".zip"
        class="upload-area"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">把 ZIP 拖到这里，或<em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">
            压缩包上限 {{ formatSize(limits.maxZipBytes) }}，可索引文件数上限 {{ limits.maxFiles }} 个
          </div>
        </template>
      </el-upload>

      <div v-if="uploadFile" class="selected-file">
        已选择：{{ uploadFile.name }}（{{ formatSize(uploadFile.size) }}）
        <el-button type="text" @click="clearFile">重新选择</el-button>
      </div>

      <el-form label-width="80px" class="upload-form">
        <el-form-item label="项目名称">
          <el-input v-model="projectName" placeholder="留空则使用压缩包文件名" maxlength="128" />
        </el-form-item>
      </el-form>

      <el-progress v-if="uploading" :percentage="uploadPercent" :stroke-width="14" />

      <template #footer>
        <el-button :disabled="uploading" @click="showUploadDialog = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadFile" @click="submitUpload">
          开始上传
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { Upload, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const POLL_INTERVAL = 2000
const STATUS_META = {
  pending: { text: '排队中', type: 'info' },
  indexing: { text: '解析中', type: 'warning' },
  ready: { text: '已就绪', type: 'success' },
  partial: { text: '部分完成', type: 'warning' },
  failed: { text: '解析失败', type: 'danger' }
}
const DEFAULT_LIMITS = { maxZipBytes: 20 * 1024 * 1024, maxFiles: 500 }

export default {
  name: 'Project',
  components: { Upload, UploadFilled },
  data() {
    return {
      projects: [],
      limits: { ...DEFAULT_LIMITS },
      loading: false,
      showUploadDialog: false,
      uploadFile: null,
      projectName: '',
      uploading: false,
      uploadPercent: 0,
      pollTimer: null
    }
  },
  computed: {
    totalChunks() {
      return this.projects.reduce((sum, item) => sum + (item.chunkCount || 0), 0)
    }
  },
  mounted() {
    this.loadProjects()
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
    async loadProjects() {
      this.loading = true
      try {
        const response = await this.$api.getProjects()
        this.projects = response.projects || []
        if (response.limits) {
          this.limits = { ...DEFAULT_LIMITS, ...response.limits }
        }
        this.syncPolling()
      } catch (error) {
        // 响应拦截器已统一提示
      } finally {
        this.loading = false
      }
    },
    syncPolling() {
      const busy = this.projects.some(
        (item) => item.status === 'pending' || item.status === 'indexing'
      )
      if (busy) {
        this.startPolling()
      } else {
        this.stopPolling()
      }
    },
    startPolling() {
      if (this.pollTimer) return
      this.pollTimer = setInterval(this.pollProjects, POLL_INTERVAL)
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
    async pollProjects() {
      try {
        const response = await this.$api.getProjects()
        this.projects = response.projects || []
      } catch (error) {
        this.stopPolling()
        return
      }
      this.syncPolling()
    },
    onFileChange(file) {
      const raw = file.raw || file
      if (!raw || !raw.name.toLowerCase().endsWith('.zip')) {
        ElMessage.warning('只支持 .zip 压缩包')
        return
      }
      if (raw.size > this.limits.maxZipBytes) {
        ElMessage.warning(`压缩包超过上限（${this.formatSize(this.limits.maxZipBytes)}）`)
        return
      }
      this.uploadFile = raw
    },
    clearFile() {
      this.uploadFile = null
    },
    resetUpload() {
      this.uploadFile = null
      this.projectName = ''
      this.uploadPercent = 0
    },
    submitUpload() {
      if (!this.uploadFile) {
        ElMessage.warning('请先选择 ZIP 压缩包')
        return
      }
      const formData = new FormData()
      formData.append('file', this.uploadFile)
      formData.append('name', this.projectName.trim())

      this.uploading = true
      this.uploadPercent = 0
      this.$api.uploadProject(formData, (event) => {
        if (event.total) {
          this.uploadPercent = Math.round((event.loaded / event.total) * 100)
        }
      }).then(() => {
        ElMessage.success('上传成功，正在后台解析项目')
        this.showUploadDialog = false
        this.resetUpload()
        this.loadProjects()
      }).catch(() => {
        // 响应拦截器已统一提示
      }).finally(() => {
        this.uploading = false
      })
    },
    openDetail(projectId) {
      this.$router.push(`/projects/${projectId}`)
    },
    async removeProject(row) {
      try {
        await ElMessageBox.confirm(
          `确定删除项目「${row.name}」及其全部知识片段吗？`,
          '提示',
          { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
        )
      } catch (error) {
        return
      }
      try {
        await this.$api.deleteProject(row.projectId)
        ElMessage.success('已删除')
        this.loadProjects()
      } catch (error) {
        // 响应拦截器已统一提示
      }
    }
  }
}
</script>

<style scoped>
.project-container {
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

.project-tip {
  margin-bottom: 12px;
}

.upload-tip {
  margin-bottom: 12px;
}

.upload-area {
  margin-bottom: 8px;
}

.selected-file {
  color: #606266;
  font-size: 13px;
  margin-bottom: 8px;
}

.upload-form {
  margin-top: 8px;
}
</style>
