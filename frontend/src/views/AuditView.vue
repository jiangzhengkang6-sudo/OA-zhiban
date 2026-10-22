<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 审计中心页面。
 *
 * 审计/运维按会话/业务号/trace/用户/动作检索事件，定位完整运行轨迹。
 */
import { onMounted, reactive, ref } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { auditApi } from '@/api'
import type { AuditEventOut } from '@/types'

const events = ref<AuditEventOut[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const route = useRoute()

const query = reactive({
  trace_id: '',
  thread_id: '',
  business_id: typeof route.query.business_id === 'string' ? route.query.business_id : '',
  actor_id: '',
  action: '',
})

const ACTIONS = [
  { value: 'session_created', label: '会话创建' },
  { value: 'intent_routed', label: '意图路由' },
  { value: 'tool_called', label: '工具调用' },
  { value: 'precheck_result', label: '预检结果' },
  { value: 'knowledge_retrieved', label: '知识检索' },
  { value: 'model_answered', label: '模型回答' },
  { value: 'human_decided', label: '人工决定' },
  { value: 'business_write', label: '业务写入' },
  { value: 'notification_sent', label: '通知发送' },
  { value: 'policy_changed', label: '配置变更' },
  { value: 'degraded', label: '降级' },
  { value: 'error_occurred', label: '异常' },
  { value: 'meeting_created', label: '会议创建' },
  { value: 'meeting_parsed', label: '会议解析' },
  { value: 'meeting_generated', label: '纪要生成' },
  { value: 'meeting_edited', label: '草稿编辑' },
  { value: 'meeting_regenerated', label: '纪要重生成' },
  { value: 'meeting_confirmed', label: '会议确认' },
  { value: 'meeting_rejected', label: '会议拒绝' },
  { value: 'meeting_paused', label: '会议暂停' },
  { value: 'meeting_resumed', label: '会议恢复' },
  { value: 'email_created', label: '邮件创建' },
  { value: 'email_analyzed', label: '邮件分析' },
  { value: 'email_edited', label: '邮件草稿编辑' },
  { value: 'email_regenerated', label: '邮件重新生成' },
  { value: 'email_confirmed', label: '邮件确认' },
  { value: 'email_rejected', label: '邮件拒绝' },
  { value: 'email_paused', label: '邮件暂停' },
  { value: 'email_resumed', label: '邮件恢复' },
  { value: 'document_created', label: '文档起草创建' },
  { value: 'document_generated', label: '文档草稿生成' },
  { value: 'document_edited', label: '文档草稿编辑' },
  { value: 'document_regenerated', label: '文档重新生成' },
  { value: 'document_confirmed', label: '文档确认' },
  { value: 'document_rejected', label: '文档拒绝' },
  { value: 'document_paused', label: '文档暂停' },
  { value: 'document_resumed', label: '文档恢复' },
  { value: 'contract_create', label: '合同创建' },
  { value: 'contract_rescan', label: '合同重新扫描' },
  { value: 'contract_review', label: '合同审查' },
  { value: 'contract_retry', label: '合同重试' },
  { value: 'contract_save', label: '合同审查保存' },
  { value: 'contract_confirm', label: '合同确认' },
  { value: 'contract_reject', label: '合同拒绝' },
  { value: 'work_task_created', label: '业务任务创建' },
  { value: 'work_task_extracted', label: '待办事项提取' },
  { value: 'work_task_saved', label: '待办事项保存' },
  { value: 'work_task_confirm', label: '待办事项确认' },
  { value: 'work_task_reject', label: '待办事项拒绝' },
  { value: 'work_task_updated', label: '业务任务更新' },
  { value: 'work_task_start', label: '业务任务开始' },
  { value: 'work_task_progress', label: '业务任务进度更新' },
  { value: 'work_task_complete', label: '业务任务完成' },
  { value: 'work_task_cancel', label: '业务任务取消' },
  { value: 'work_task_archive', label: '业务任务归档' },
  { value: 'report_created', label: '报表创建' },
  { value: 'report_plan_approved', label: '报表统计方案确认' },
  { value: 'report_retried', label: '报表重试' },
  { value: 'report_edited', label: '报表草稿编辑' },
  { value: 'report_published', label: '报表发布' },
  { value: 'leave_attachment_upload', label: '请假附件上传' },
  { value: 'leave_attachment_download', label: '请假附件下载' },
  { value: 'leave_attachment_scan', label: '请假附件扫描' },
  { value: 'audit_export_created', label: '审计记录导出' },
]

const ACTION_LABELS = Object.fromEntries(ACTIONS.map((item) => [item.value, item.label]))
const DECISION_LABELS: Record<string, string> = {
  approve: '批准',
  edit: '编辑后批准',
  reject: '驳回',
  confirm: '确认',
  cancel: '取消',
  escalate: '超时升级',
}

const SCENE_LABELS: Record<string, string> = {
  leave: '请假审批', faq: '知识问答', ticket: '工单服务', document: '文档起草',
  email: '邮件工作台', meeting: '会议文本', work_task: '业务任务', report: '只读报表', contract: '合同审查',
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] || '业务操作'
}

function detailOf(row: AuditEventOut): string {
  const input = row.input_summary || {}
  const output = row.output_summary || {}
  if (row.action === 'human_decided') {
    const action = String(input.action || '')
    const comment = String(input.comment || '')
    return `${DECISION_LABELS[action] || action || '人工处理'}${comment ? `：${comment}` : ''}`
  }
  if (row.action === 'business_write') {
    const target = row.target_id ? `审批号 ${row.target_id}` : 'OA 业务数据'
    const status = output.status ? `，状态 ${output.status}` : ''
    return `写入 ${target}${status}`
  }
  if (row.action === 'precheck_result') {
    return input.passed ? `预检通过（规则 ${input.rule_version || '-'}）` : '预检未通过'
  }
  if (row.action === 'notification_sent') return '发送审批通知/催办'
  if (row.action === 'policy_changed') {
    const scene = String(input.scene || row.target_id || '')
    return `${SCENE_LABELS[scene] || '业务场景'}策略已更新`
  }
  return row.target_id || '-'
}

function formatTime(value?: string | null): string {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
    for (const [k, v] of Object.entries(query)) {
      if (v) params[k] = v
    }
    const res = await auditApi.query(params)
    events.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function exportCurrent() {
  const filters: Record<string, any> = {}
  for (const [key, value] of Object.entries(query)) {
    if (value) filters[key] = value
  }
  const record = await auditApi.export(filters)
  const blob = await auditApi.download(record.id)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'audit-export-' + record.id + '.json'
  anchor.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出 ' + record.row_count + ' 条审计记录')
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header><span>审计事件查询</span></template>

    <el-form inline>
      <el-form-item label="追踪 ID">
        <el-input v-model="query.trace_id" placeholder="追踪 ID" clearable style="width: 200px" />
      </el-form-item>
      <el-form-item label="会话 ID">
        <el-input v-model="query.thread_id" placeholder="会话 UUID" clearable style="width: 220px" />
      </el-form-item>
      <el-form-item label="业务号">
        <el-input v-model="query.business_id" placeholder="业务单据号" clearable style="width: 160px" />
      </el-form-item>
      <el-form-item label="操作者">
        <el-input v-model="query.actor_id" placeholder="用户 ID" clearable style="width: 130px" />
      </el-form-item>
      <el-form-item label="动作">
        <el-select v-model="query.action" placeholder="全部" clearable style="width: 180px">
          <el-option v-for="a in ACTIONS" :key="a.value" :label="a.label" :value="a.value" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="page = 1; load()">查询</el-button>
        <el-button :icon="Download" @click="exportCurrent">导出当前筛选</el-button>
      </el-form-item>
    </el-form>

    <el-table :data="events" v-loading="loading" border size="small" style="margin-top: 8px">
      <el-table-column prop="id" label="#" width="70" />
      <el-table-column label="动作" width="120">
        <template #default="{ row }">{{ actionLabel(row.action) }}</template>
      </el-table-column>
      <el-table-column prop="thread_id" label="会话 ID" min-width="170" show-overflow-tooltip />
      <el-table-column prop="business_id" label="业务号" width="130" />
      <el-table-column prop="actor_id" label="操作者" width="120" />
      <el-table-column label="详情" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">{{ detailOf(row) }}</template>
      </el-table-column>
      <el-table-column prop="trace_id" label="追踪 ID" min-width="170" show-overflow-tooltip />
      <el-table-column label="结果" width="80">
        <template #default="{ row }">
          <el-tag :type="row.result === 'fail' ? 'danger' : 'success'" size="small">{{ row.result }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="北京时间" width="185">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      style="margin-top: 12px; justify-content: flex-end"
      @current-change="load"
    />
  </el-card>
</template>
