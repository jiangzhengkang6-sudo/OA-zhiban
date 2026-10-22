<script setup lang="ts">
import { computed } from 'vue'
import type { MeetingDraft, MeetingSegment } from '@/types'
const props = defineProps<{ modelValue: MeetingDraft; segments: MeetingSegment[]; editable: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [draft: MeetingDraft] }>()
const refs = computed(() => new Map(props.segments.map(s => [s.segment_id, s.ordinal])))
const defaultRef = computed(() => props.modelValue.source_refs.find(id => refs.value.has(id)) || props.segments[0]?.segment_id)
function update<K extends keyof MeetingDraft>(field: K, value: MeetingDraft[K]) { emit('update:modelValue', { ...props.modelValue, [field]: value }) }
function addTopic() { update('topics', [...props.modelValue.topics, '新议题']) }
function removeTopic(index: number) { update('topics', props.modelValue.topics.filter((_, i) => i !== index)) }
function addDecision() {
  if (!defaultRef.value) return
  update('decisions', [...props.modelValue.decisions, { text: '待核对的决策', source_refs: [defaultRef.value], confidence: 'needs_confirmation' }])
}
function removeDecision(index: number) { update('decisions', props.modelValue.decisions.filter((_, i) => i !== index)) }
function addAction() {
  if (!defaultRef.value) return
  update('action_items', [...props.modelValue.action_items, { title: '待核对的待办', assignee_candidate: null, due_at_candidate: null, priority: 'medium', source_refs: [defaultRef.value], needs_confirmation: true }])
}
function removeAction(index: number) { update('action_items', props.modelValue.action_items.filter((_, i) => i !== index)) }
function setRefs(field: 'decisions' | 'action_items', index: number, value: string[]) {
  const entries = [...props.modelValue[field]]
  entries[index] = { ...entries[index], source_refs: value }
  emit('update:modelValue', { ...props.modelValue, [field]: entries })
}
function setSummary(value: string) { emit('update:modelValue', { ...props.modelValue, summary: value }) }
function setTopic(index: number, value: string) { const topics = [...props.modelValue.topics]; topics[index] = value; emit('update:modelValue', { ...props.modelValue, topics }) }
function setDecision(index: number, value: string) { const decisions = [...props.modelValue.decisions]; decisions[index] = { ...decisions[index], text: value }; emit('update:modelValue', { ...props.modelValue, decisions }) }
function setAction(index: number, field: 'title' | 'assignee_candidate' | 'due_at_candidate' | 'priority', value: string) {
  const action_items = [...props.modelValue.action_items]
  action_items[index] = { ...action_items[index], [field]: value || null, needs_confirmation: !((field === 'assignee_candidate' ? value : action_items[index].assignee_candidate) && (field === 'due_at_candidate' ? value : action_items[index].due_at_candidate)) }
  emit('update:modelValue', { ...props.modelValue, action_items })
}
</script>

<template>
  <section class="draft-editor" aria-label="会议草稿">
    <div class="section-title"><h2>纪要草稿</h2><span>逐项核对后再确认</span></div>
    <label class="field-label" for="meeting-summary">纪要摘要</label>
    <el-input id="meeting-summary" :model-value="modelValue.summary" aria-label="纪要摘要" type="textarea" :rows="4" :disabled="!editable" @update:model-value="setSummary" />
    <label class="field-label source-label" for="meeting-summary-sources">纪要来源</label>
    <el-select id="meeting-summary-sources" :model-value="modelValue.source_refs" aria-label="纪要来源" multiple placeholder="选择来源片段" :disabled="!editable" @update:model-value="update('source_refs', $event)"><el-option v-for="segment in segments" :key="segment.segment_id" :label="`来源 ${segment.ordinal}`" :value="segment.segment_id" /></el-select>
    <div class="refs"><a v-for="id in modelValue.source_refs" :key="id" :href="`#source-${id}`">来源 {{ refs.get(id) || '?' }}</a></div>
    <div class="group"><div class="group-heading"><h3>议题 <small>{{ modelValue.topics.length }}</small></h3><el-button v-if="editable" text data-testid="add-topic" @click="addTopic">添加议题</el-button></div>
      <div v-for="(topic, index) in modelValue.topics" :key="index" class="entry"><span class="number">{{ String(index + 1).padStart(2, '0') }}</span><el-input :model-value="topic" :aria-label="`议题 ${index + 1}`" :disabled="!editable" @update:model-value="setTopic(index, $event)" /><el-button v-if="editable" text :data-testid="`remove-topic-${index}`" @click="removeTopic(index)">删除</el-button></div>
      <p v-if="!modelValue.topics.length" class="hint">暂无明确议题。</p>
    </div>
    <div class="group"><div class="group-heading"><h3>决策候选 <small>{{ modelValue.decisions.length }}</small></h3><el-button v-if="editable" text data-testid="add-decision" :disabled="!defaultRef" @click="addDecision">添加决策</el-button></div>
      <article v-for="(decision, index) in modelValue.decisions" :key="index" class="entry-card"><el-input :model-value="decision.text" :aria-label="`决策 ${index + 1}`" type="textarea" :rows="2" :disabled="!editable" @update:model-value="setDecision(index, $event)" /><el-select v-if="editable" :model-value="decision.source_refs" :aria-label="`决策来源 ${index + 1}`" multiple placeholder="选择来源片段" @update:model-value="setRefs('decisions', index, $event)"><el-option v-for="segment in segments" :key="segment.segment_id" :label="`来源 ${segment.ordinal}`" :value="segment.segment_id" /></el-select><div class="refs"><a v-for="id in decision.source_refs" :key="id" :href="`#source-${id}`">来源 {{ refs.get(id) || '?' }}</a><span v-if="decision.confidence !== 'explicit'">待人工核对</span></div><el-button v-if="editable" text :data-testid="`remove-decision-${index}`" @click="removeDecision(index)">删除决策</el-button></article>
      <p v-if="!modelValue.decisions.length" class="hint">暂无可确认的决策。</p>
    </div>
    <div class="group"><div class="group-heading"><h3>待办候选 <small>{{ modelValue.action_items.length }}</small></h3><el-button v-if="editable" text data-testid="add-action" :disabled="!defaultRef" @click="addAction">添加待办</el-button></div>
      <article v-for="(item, index) in modelValue.action_items" :key="index" class="entry-card"><el-input :model-value="item.title" :aria-label="`待办 ${index + 1}`" :disabled="!editable" @update:model-value="setAction(index, 'title', $event)" />
        <div class="action-fields"><el-input :model-value="item.assignee_candidate || ''" :aria-label="`负责人 ${index + 1}`" placeholder="负责人待确认" :disabled="!editable" @update:model-value="setAction(index, 'assignee_candidate', $event)" /><el-input :model-value="item.due_at_candidate || ''" :aria-label="`截止时间 ${index + 1}`" placeholder="截止时间待确认" :disabled="!editable" @update:model-value="setAction(index, 'due_at_candidate', $event)" /><el-select :model-value="item.priority" :aria-label="`优先级 ${index + 1}`" :disabled="!editable" @update:model-value="setAction(index, 'priority', $event)"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /></el-select></div>
        <el-select v-if="editable" :model-value="item.source_refs" :aria-label="`待办来源 ${index + 1}`" multiple placeholder="选择来源片段" @update:model-value="setRefs('action_items', index, $event)"><el-option v-for="segment in segments" :key="segment.segment_id" :label="`来源 ${segment.ordinal}`" :value="segment.segment_id" /></el-select><div class="refs"><a v-for="id in item.source_refs" :key="id" :href="`#source-${id}`">来源 {{ refs.get(id) || '?' }}</a><span v-if="item.needs_confirmation">信息待确认</span></div><el-button v-if="editable" text :data-testid="`remove-action-${index}`" @click="removeAction(index)">删除待办</el-button></article>
      <p v-if="!modelValue.action_items.length" class="hint">暂无待办候选。</p>
    </div>
  </section>
</template>

<style scoped>
.draft-editor { min-width: 0; }
.section-title { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.section-title h2 { margin: 0 0 20px; font-size: 18px; color: #17324d; }
.section-title span,.hint,.group small { font-size: 13px; color: #657e91; }
.field-label { display: block; margin: 0 0 9px; font-weight: 600; color: #284258; }
.source-label { margin-top: 16px; }
.group { border-top: 1px solid #e4ecef; padding-top: 17px; margin-top: 24px; }
.group h3 { font-size: 15px; color: #24445b; margin: 0 0 14px; }
.group-heading { display: flex; justify-content: space-between; align-items: center; }
.group small { margin-left: 5px; }
.entry { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.number { color: #41818d; font-size: 12px; font-weight: 700; }
.entry-card { background: #f8fbfc; border: 1px solid #e0eaed; border-radius: 10px; padding: 14px; margin-bottom: 12px; }
.action-fields { display: grid; grid-template-columns: 1fr 1fr 110px; gap: 8px; margin-top: 10px; }
.refs { display: flex; gap: 9px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
.refs a { color: #157a89; text-decoration: none; background: #e8f5f5; border-radius: 6px; padding: 4px 8px; }
.refs a:hover { text-decoration: underline; }
.refs span { color: #805d2e; background: #fff3df; border-radius: 6px; padding: 4px 8px; }
@media (max-width: 800px) { .action-fields { grid-template-columns: 1fr; } }
</style>
