<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 审批卡片组件。
 *
 * 供审批人查看审批链并提交 approve/edit/reject 决定，附带意见输入。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getCurrentUserId } from '@/api/client'
import type { ThreadDetail } from '@/types'
import { localDateTime } from '@/utils/leave'

const props = defineProps<{
  route?: { nodes?: Array<{ order: number; approver_id: string; approver_name: string; is_proxy: boolean }>; risk_hint?: string } | null
  interruptId?: string | null
  detail: ThreadDetail
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', action: string, comment: string, editedData?: Record<string, unknown>): void
}>()

const comment = ref('')
const rejectCategory = ref('other')
const editing = ref(false)
const form = reactive({ reason: '', start_at: '', end_at: '' })
const canApprove = computed(() => !!(props.interruptId || props.detail.application_id)
  && props.detail.status === 'WAITING_HUMAN' && props.detail.active_approval_node?.approver_id === getCurrentUserId())
watch(() => props.detail.form_snapshot, (snapshot) => {
  form.reason = String(snapshot?.reason || '')
  form.start_at = localDateTime(snapshot?.start_at)
  form.end_at = localDateTime(snapshot?.end_at)
  editing.value = false
}, { immediate: true })

async function submit(action: string) {
  if (!canApprove.value || props.loading) return
  if (action === 'reject' && !comment.value.trim()) {
    ElMessage.warning('驳回时请填写原因')
    return
  }
  if (action === 'reject') {
    emit('submit', action, comment.value, { reason_category: rejectCategory.value })
    return
  }
  if (action === 'edit') {
    if (!editing.value) { editing.value = true; return }
    const original = props.detail.form_snapshot || {}
    const edited: Record<string, unknown> = {}
    for (const key of ['reason', 'start_at', 'end_at'] as const) {
      if (form[key] !== (key === 'reason' ? String(original[key] || '') : localDateTime(original[key]))) {
        if (key !== 'reason' && (!form[key] || Number.isNaN(new Date(form[key]).getTime()))) { ElMessage.warning('请填写有效的开始和结束时间'); return }
        edited[key] = key === 'reason' ? form[key] : new Date(form[key]).toISOString()
      }
    }
    if (!comment.value.trim() || !Object.keys(edited).length) {
      ElMessage.warning('请修改表单字段并填写编辑原因')
      return
    }
    emit('submit', action, comment.value, edited)
    return
  }
  emit('submit', action, comment.value)
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <span>审批链</span>
    </template>
    <el-steps :active="Math.max(0, (detail.active_approval_node?.order || route?.nodes?.length || 1) - 1)" align-center direction="horizontal">
      <el-step
        v-for="n in route?.nodes || []"
        :key="n.order"
        :title="n.approver_name"
        :description="n.is_proxy ? '代理人' : `第 ${n.order} 级`"
      />
    </el-steps>
    <el-alert
      v-if="route?.risk_hint"
      :title="route.risk_hint"
      type="warning"
      :closable="false"
      show-icon
      style="margin-top: 12px"
    />
    <div class="active-node" v-if="detail.active_approval_node">
      当前待办：第 {{ detail.active_approval_node.order }} 级 · {{ detail.active_approval_node.approver_name }}
    </div>
    <el-alert v-if="!canApprove" title="仅当前节点审批人可提交决定" type="info" :closable="false" style="margin-top: 12px" />

    <div v-if="editing && canApprove" class="edit-form">
      <el-input v-model="form.reason" placeholder="请假原因" aria-label="编辑请假原因" />
      <el-input v-model="form.start_at" type="datetime-local" aria-label="编辑开始时间" />
      <el-input v-model="form.end_at" type="datetime-local" aria-label="编辑结束时间" />
    </div>

    <el-input
      v-model="comment"
      type="textarea"
      :rows="2"
      :placeholder="editing ? '编辑原因（必填）' : '审批意见；驳回时必填'"
      style="margin-top: 12px"
    />
    <el-select v-model="rejectCategory" aria-label="驳回理由分类" style="margin-top: 12px; width: 100%">
      <el-option label="其他原因" value="other" />
      <el-option label="申请材料" value="materials" />
      <el-option label="制度不符" value="policy" />
      <el-option label="假期余额" value="balance" />
      <el-option label="时间安排" value="scheduling" />
    </el-select>
    <div style="margin-top: 12px; text-align: right">
      <el-button type="success" :disabled="!canApprove || loading" :loading="loading" @click="submit('approve')">批准当前级</el-button>
      <el-button type="warning" :disabled="!canApprove || loading" @click="submit('edit')">{{ editing ? '确认编辑并重检' : '编辑后批准' }}</el-button>
      <el-button type="danger" :disabled="!canApprove || loading" @click="submit('reject')">驳回</el-button>
    </div>
  </el-card>
</template>
<style scoped>
.active-node { margin-top: 16px; padding: 12px 16px; border-radius: 10px; background: #e8f4f2; color: #155e59; font-weight: 600; }
.edit-form { display: grid; gap: 12px; margin-top: 16px; }
</style>
