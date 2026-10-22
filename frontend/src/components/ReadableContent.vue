<script setup lang="ts">
import { computed } from 'vue'
import { businessLabel, personName } from '@/utils/businessLabels'

const props = withDefaults(defineProps<{ value: unknown; field?: string }>(), { field: '' })
const fieldLabels: Record<string, string> = {
  summary: '内容摘要', action_items: '待办事项', title: '事项', content: '内容', text: '内容',
  messages: '历史对话', extracted_fields: '问题信息', feedback: '用户反馈', faq_sources: '参考资料',
  impact: '影响范围', category: '问题类别', priority: '优先级', role: '发言人',
  assignee_candidate: '建议负责人', due_at_candidate: '建议截止时间', needs_confirmation: '需要人工核实',
  assignee_id: '负责人', user_id: '用户', status: '处理状态', scene: '服务类型', business_id: '业务编号',
  ticket_id: '工单编号', due_at: '截止时间', progress: '完成进度', comment: '处理备注',
  answer: '参考回答', document_id: '文档编号', source_location: '来源位置', similarity: '匹配程度',
  document_title: '文档标题', location: '来源位置', confidence: '可信程度', topics: '议题', decisions: '决议',
}
// Internal references remain in the stored snapshot and the source navigation.
const hidden = new Set(['thread_id', 'reason_code', 'source_refs', 'segment_id', 'content_hash', 'text_hash'])
const entries = computed(() => props.value && typeof props.value === 'object' && !Array.isArray(props.value)
  ? Object.entries(props.value).filter(([key]) => !hidden.has(key)) : [])
const scalar = computed(() => {
  if (props.value == null || props.value === '') return '未提供'
  if (typeof props.value === 'boolean') return props.value ? '是' : '否'
  const text = String(props.value)
  if (['assignee_id', 'user_id', 'assignee_candidate'].includes(props.field)) return personName(text)
  return ['priority', 'role', 'status', 'scene', 'confidence'].includes(props.field) ? businessLabel(text) : text
})
</script>

<template>
  <ol v-if="Array.isArray(value) && value.length" class="readable-items">
    <li v-for="(entry, index) in value" :key="index"><ReadableContent :value="entry" /></li>
  </ol>
  <p v-else-if="Array.isArray(value)" class="readable-text muted">暂无记录</p>
  <dl v-else-if="value && typeof value === 'object' && entries.length" class="readable-fields">
    <template v-for="[key, entry] in entries" :key="key">
      <dt>{{ fieldLabels[key] || '补充信息' }}</dt><dd><ReadableContent :value="entry" :field="key" /></dd>
    </template>
  </dl>
  <p v-else-if="value && typeof value === 'object'" class="readable-text muted">暂无补充信息</p>
  <p v-else class="readable-text">{{ scalar }}</p>
</template>

<style scoped>
.readable-fields { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 10px 14px; margin: 0; }
.readable-fields dt { color: #697883; font-size: 13px; line-height: 1.8; }
.readable-fields dd { margin: 0; min-width: 0; }
.readable-text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.readable-items { margin: 0; padding-left: 20px; }
.readable-items > li + li { margin-top: 16px; }
@media(max-width:600px) { .readable-fields { grid-template-columns: 1fr; gap: 4px; } .readable-fields dd { margin-bottom: 8px; } }
</style>
