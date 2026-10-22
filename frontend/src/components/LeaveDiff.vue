<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ before?: Record<string, any>; after?: Record<string, any> }>()
const labels: Record<string, string> = { leave_type: '假期类型', start_at: '开始时间', end_at: '结束时间', reason: '请假原因', attachments: '附件' }
const text = (value: any) => Array.isArray(value) ? value.join('、') || '无' : String(value ?? '—')
const changes = computed(() => Object.keys(labels).filter(key => JSON.stringify(props.before?.[key]) !== JSON.stringify(props.after?.[key]))
  .map(key => ({ field: labels[key], before: text(props.before?.[key]), after: text(props.after?.[key]) })))
</script>
<template>
  <el-table v-if="changes.length" :data="changes" border><el-table-column prop="field" label="字段" width="120" /><el-table-column prop="before" label="原版本" /><el-table-column prop="after" label="当前内容" /></el-table>
  <p v-else class="muted">表单字段没有变化</p>
</template>
