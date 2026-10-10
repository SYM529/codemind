<template>
  <div v-if="debug" class="debug-content">
    <el-descriptions title="模型调用信息" :column="2" border>
      <el-descriptions-item label="框架">{{ config.framework }}</el-descriptions-item>
      <el-descriptions-item label="模型">{{ debug.model }}</el-descriptions-item>
      <el-descriptions-item label="提供商">{{ debug.provider }}</el-descriptions-item>
      <el-descriptions-item label="耗时">{{ debug.durationMs }} ms</el-descriptions-item>
      <el-descriptions-item label="Prompt 版本">{{ debug.promptVersion }}</el-descriptions-item>
      <el-descriptions-item label="输出格式">{{ debug.outputFormat }}</el-descriptions-item>
      <el-descriptions-item label="输入 Token">{{ debug.usage.estimatedInputTokens }}</el-descriptions-item>
      <el-descriptions-item label="输出 Token">{{ debug.usage.estimatedOutputTokens }}</el-descriptions-item>
      <el-descriptions-item label="成本">US$ {{ debug.usage.estimatedCostUsd || 0 }}</el-descriptions-item>
      <el-descriptions-item label="计量来源">
        <el-tag size="small" :type="debug.usage.source === 'api' ? 'success' : 'info'">
          {{ debug.usage.source === 'api' ? '模型返回' : (debug.usage.source === 'cache' ? '缓存命中' : '估算') }}
        </el-tag>
      </el-descriptions-item>
    </el-descriptions>

    <el-divider content-position="left">缓存与结果质量</el-divider>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="语义缓存">
        <el-tag size="small" :type="debug.cache && debug.cache.hit ? 'success' : 'info'">
          {{ debug.cache && debug.cache.hit ? `命中（${debug.cache.score}）` : '未命中' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item v-if="debug.evaluation" label="函数覆盖率">
        {{ (debug.evaluation.functionCoverage * 100).toFixed(1) }}%
      </el-descriptions-item>
      <el-descriptions-item v-if="debug.evaluation" label="行号有效率">
        {{ (debug.evaluation.validLineRate * 100).toFixed(1) }}%
      </el-descriptions-item>
      <el-descriptions-item v-if="debug.evaluation" label="识别/生成">
        {{ debug.evaluation.functionCount }} / {{ debug.evaluation.commentCount }}
      </el-descriptions-item>
    </el-descriptions>

    <el-divider content-position="left">RAG 检索增强</el-divider>
    <template v-if="debug.rag">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="命中片段数">{{ debug.rag.retrievedCount }}</el-descriptions-item>
        <el-descriptions-item label="注入上下文字符数">{{ debug.rag.contextChars }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="debug.rag.retrieved && debug.rag.retrieved.length" class="rag-hits">
        <div v-for="(hit, index) in debug.rag.retrieved" :key="index" class="rag-hit">
          <span class="rag-hit-title">{{ hit.title }} · 第 {{ hit.chunkIndex + 1 }} 块</span>
          <el-tag size="small" type="success">相关度 {{ hit.score }}</el-tag>
          <pre class="rag-hit-preview">{{ hit.preview }}</pre>
        </div>
      </div>
      <el-alert
        v-else
        title="知识库为空或未命中，可在“知识库”页面添加文档后重试"
        type="warning"
        :closable="false"
        show-icon
      />
    </template>

    <el-divider content-position="left">结构化模型输出</el-divider>
    <pre class="debug-json">{{ formattedResult }}</pre>
  </div>
  <div v-else class="empty-state">
    <el-empty description="生成 AI 结果后查看调试信息" />
  </div>
</template>

<script>
export default {
  name: 'DebugPanel',
  props: {
    debug: { type: Object, default: null },
    config: { type: Object, default: () => ({}) },
    formattedResult: { type: String, default: '' }
  }
}
</script>

<style scoped>
.debug-content {
  height: 500px;
  overflow-y: auto;
}

.debug-json {
  background: #F7F9FC;
  color: #47536B;
  border: 1px solid #E8ECF3;
  padding: 15px;
  border-radius: 8px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  line-height: 1.5;
}

.rag-hits {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rag-hit {
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.rag-hit-title {
  font-weight: bold;
  color: #6E7DF0;
  font-size: 13px;
}

.rag-hit-preview {
  width: 100%;
  margin: 0;
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  line-height: 1.4;
  max-height: 120px;
  overflow: auto;
}

.empty-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
