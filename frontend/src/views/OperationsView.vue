<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { operationsApi } from '@/api'
import type { RuntimeMetrics, RuntimeTraceDetail } from '@/types'
import RuntimeTrace from '@/components/RuntimeTrace.vue'

const metrics = ref<RuntimeMetrics | null>(null)
const traceId = ref('')
const trace = ref<RuntimeTraceDetail | null>(null)
const loading = ref(false)
async function loadMetrics() { loading.value = true; try { metrics.value = await operationsApi.metrics() } finally { loading.value = false } }
async function loadTrace() { if (!traceId.value.trim()) { ElMessage.warning('请输入 trace_id'); return }; trace.value = await operationsApi.trace(traceId.value.trim()) }
onMounted(loadMetrics)
</script>

<template>
  <div class="workbench">
    <div class="page-heading"><div><span class="eyebrow">OPERATIONS</span><h1>运维观测</h1><p class="muted">从整体运行指标下钻到单次 trace，token 缺失会明确标记。</p></div><el-button :loading="loading" @click="loadMetrics">刷新指标</el-button></div>
    <div v-if="metrics" class="metric-grid">
      <el-card shadow="never"><span class="metric-label">Span 数量</span><strong>{{ metrics.span_count }}</strong></el-card>
      <el-card shadow="never"><span class="metric-label">错误数量</span><strong class="danger">{{ metrics.error_count }}</strong></el-card>
      <el-card shadow="never"><span class="metric-label">平均耗时</span><strong>{{ metrics.avg_duration_ms ?? '-' }}<small> ms</small></strong></el-card>
      <el-card shadow="never"><span class="metric-label">Token 缺失</span><strong class="warning">{{ metrics.usage_missing_count }}</strong></el-card>
    </div>
    <el-card shadow="never" class="surface"><template #header><span>Trace 下钻</span></template><div class="trace-search"><el-input v-model="traceId" placeholder="输入 trace_id" clearable @keyup.enter="loadTrace" /><el-button type="primary" @click="loadTrace">查看</el-button></div><RuntimeTrace :trace="trace" /></el-card>
  </div>
</template>

<style scoped>
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-grid .el-card { border: 1px solid #dce5ed; }
.metric-label { display: block; color: #64788b; font-size: 13px; margin-bottom: 10px; }
.metric-grid strong { font-size: 25px; color: #17324d; }
.metric-grid small { font-size: 12px; font-weight: 400; }
.danger { color: #c2410c !important; }.warning { color: #a16207 !important; }
.trace-search { display: flex; gap: 10px; max-width: 560px; margin-bottom: 18px; }
@media (max-width: 800px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
