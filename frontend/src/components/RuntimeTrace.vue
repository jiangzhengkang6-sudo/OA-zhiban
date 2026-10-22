<script setup lang="ts">
import type { RuntimeTraceDetail } from '@/types'
defineProps<{ trace: RuntimeTraceDetail | null }>()
</script>

<template>
  <div v-if="trace" class="runtime-trace">
    <div class="trace-heading"><strong>{{ trace.trace_id }}</strong><span>{{ trace.spans.length }} 个运行 Span</span></div>
    <el-timeline v-if="trace.spans.length">
      <el-timeline-item v-for="span in trace.spans" :key="span.id" :timestamp="span.started_at || '-'" :type="span.status === 'error' ? 'danger' : 'primary'">
        <div class="trace-row"><strong>{{ span.node_name }}</strong><el-tag size="small" :type="span.status === 'error' ? 'danger' : 'success'">{{ span.status }}</el-tag></div>
        <div class="muted">{{ span.tool_name || '节点运行' }} · {{ span.duration_ms ?? '-' }} ms<span v-if="span.error_code"> · {{ span.error_code }}</span></div>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-else description="暂无运行 Span" />
    <div v-if="trace.model_usage.length" class="usage-list">
      <div class="usage-title">模型用量</div>
      <div v-for="usage in trace.model_usage" :key="usage.id" class="usage-row"><span>{{ usage.provider }} / {{ usage.model_name }}</span><el-tag v-if="usage.usage_missing" type="warning" size="small">token 未知</el-tag><span v-else>{{ usage.total_tokens }} tokens</span></div>
    </div>
  </div>
</template>

<style scoped>
.runtime-trace { padding-top: 4px; }
.trace-heading, .trace-row, .usage-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.trace-heading { margin-bottom: 18px; color: #17324d; }
.trace-heading span, .muted { color: #64788b; font-size: 12px; }
.trace-row { margin-bottom: 4px; }
.usage-list { border-top: 1px solid #e1eaf0; padding-top: 14px; margin-top: 8px; }
.usage-title { font-weight: 600; margin-bottom: 8px; }
.usage-row { padding: 8px 0; border-bottom: 1px solid #edf1f5; font-size: 13px; }
</style>
