<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 请假任务详情页面。
 *
 * 展示表单快照、预检结果、审批链、操作记录，并支持审批人提交批准/驳回决定。
 */
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { approvalApi, interruptApi, threadApi, leaveApi } from '@/api'
import { getCurrentUserId } from '@/api/client'
import type { ThreadDetail, LeaveAttachment } from '@/types'
import StatusTag from '@/components/StatusTag.vue'
import PrecheckTable from '@/components/PrecheckTable.vue'
import ApprovalCard from '@/components/ApprovalCard.vue'

const route = useRoute()
const detail = ref<ThreadDetail | null>(null)
const loading = ref(false)
const fetching = ref(false), error = ref('')
const attachments = ref<LeaveAttachment[]>([])
const attachmentError = ref(''), attachmentLoading = ref(false), downloading = ref('')
const commandKeys = new Map<string, string>()

async function loadAttachments() {
  const id = detail.value?.application_id
  if (!id) return
  attachmentLoading.value = true; attachmentError.value = ''; attachments.value = []
  try { attachments.value = await leaveApi.attachments(id) }
  catch { attachmentError.value = '无法加载证明材料，请重试' }
  finally { attachmentLoading.value = false }
}
function scanLabel(status: string) {
  return ({ PENDING: '待扫描', CLEAN: '扫描通过', INFECTED: '检测到风险', ERROR: '扫描失败' } as Record<string, string>)[status] || '状态未知'
}
async function downloadAttachment(item: LeaveAttachment) {
  if (!detail.value?.application_id || item.scan_status !== 'CLEAN' || downloading.value) return
  downloading.value = item.attachment_id
  let url = ''
  try {
    const content = await leaveApi.downloadAttachment(detail.value.application_id, item.attachment_id)
    url = URL.createObjectURL(content)
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = item.filename
    document.body.appendChild(anchor); anchor.click(); anchor.remove()
  } catch { /* 客户端显示下载错误。 */ }
  finally { if (url) URL.revokeObjectURL(url); downloading.value = '' }
}

/** 加载详情 */
async function load() {
  const threadId = route.params.threadId as string
  if (!threadId) return
  fetching.value = true; error.value = ''; detail.value = null
  attachments.value = []; attachmentError.value = ''
  try { detail.value = await threadApi.get(threadId); await loadAttachments() }
  catch { error.value = '无法加载审批材料，请确认你是当前节点审批人或申请人' }
  finally { fetching.value = false }
}

/** 提交审批决定 */
async function submit(action: string, comment: string, editedData?: Record<string, unknown>) {
  if (loading.value) return
  if (!detail.value?.current_interrupt_id && !detail.value?.application_id) {
    ElMessage.warning('当前无待处理的审批中断')
    return
  }
  loading.value = true
  try {
    const fingerprint = JSON.stringify([detail.value.thread_id, detail.value.active_approval_node?.node_id, action, comment, editedData])
    if (!commandKeys.has(fingerprint)) commandKeys.set(fingerprint, crypto.randomUUID())
    const payload = {
      action,
      comment,
      edited_data: editedData,
      idempotency_key: commandKeys.get(fingerprint),
    }
    if (detail.value.application_id) await leaveApi.decide(detail.value.application_id, payload)
    else await interruptApi.resume(detail.value.current_interrupt_id!, payload)
    ElMessage.success('已提交决定')
    await load()
  } catch { /* 保留同一载荷幂等键，允许安全重试。 */
  } finally {
    loading.value = false
  }
}

async function reconcile() {
  if (!detail.value || loading.value) return
  loading.value = true
  try {
    if (detail.value.approval_recovery_action === 'retry') {
      await approvalApi.retryWrite(detail.value.thread_id)
    } else {
      await approvalApi.reconcile(detail.value.thread_id)
    }
    ElMessage.success('权威审批结果已核对')
    await load()
  } finally {
    loading.value = false
  }
}

watch(() => route.params.threadId, load, { immediate: true })
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="header">
        <span>请假任务详情</span>
        <StatusTag :status="detail?.status" />
      </div>
    </template>

    <el-skeleton v-if="fetching" :rows="8" animated />
    <el-result v-else-if="error" icon="warning" :title="error"><template #extra><el-button @click="load">重新加载</el-button></template></el-result>
    <template v-else-if="detail">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="会话 ID">{{ detail.thread_id }}</el-descriptions-item>
        <el-descriptions-item label="业务单据号">{{ detail.business_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="场景">请假审批</el-descriptions-item>
        <el-descriptions-item label="当前状态">{{ detail.status }}</el-descriptions-item>
      </el-descriptions>

      <h4>预检结果</h4>
      <el-alert v-if="detail.error?.code === 'LEGACY_RECONCILE'" type="warning"
        :title="detail.error.msg" :closable="false" show-icon />
      <PrecheckTable :precheck="detail.precheck" />

      <h4>申请材料</h4>
      <el-descriptions v-if="detail.form_snapshot" :column="2" border>
        <el-descriptions-item label="假期类型">{{ detail.form_snapshot.leave_type }}</el-descriptions-item>
        <el-descriptions-item label="申请人">{{ detail.form_snapshot.user_id }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ detail.form_snapshot.start_at }}</el-descriptions-item>
        <el-descriptions-item label="结束时间">{{ detail.form_snapshot.end_at }}</el-descriptions-item>
        <el-descriptions-item label="请假原因" :span="2">{{ detail.form_snapshot.reason || '-' }}</el-descriptions-item>
        <el-descriptions-item v-if="!detail.application_id" label="附件" :span="2">{{ detail.form_snapshot.attachments?.join('、') || '无' }}</el-descriptions-item>
      </el-descriptions>
      <section v-if="detail.application_id" class="attachment-panel" aria-label="证明材料">
        <h4>证明材料</h4>
        <p v-if="attachmentLoading" role="status">正在加载证明材料…</p>
        <div v-else-if="attachmentError" role="alert" class="actions">{{ attachmentError }}<el-button text @click="loadAttachments">重新加载附件</el-button></div>
        <ul v-else-if="attachments.length" class="attachment-list">
          <li v-for="item in attachments" :key="item.attachment_id" class="attachment-row">
            <div class="attachment-description"><strong>{{ item.filename }}</strong><span class="muted">{{ item.content_type }} · {{ item.size_bytes }} B</span></div>
            <div class="actions"><el-tag :type="item.scan_status === 'CLEAN' ? 'success' : item.scan_status === 'PENDING' ? 'warning' : 'danger'">{{ scanLabel(item.scan_status) }}</el-tag>
              <el-button :disabled="item.scan_status !== 'CLEAN' || !!downloading" :loading="downloading === item.attachment_id" @click="downloadAttachment(item)">下载</el-button>
            </div>
          </li>
        </ul>
        <p v-else class="muted">暂无证明材料。</p>
      </section>

      <h4>审批链与决策</h4>
      <ApprovalCard
        v-if="detail.status === 'WAITING_HUMAN'"
        :route="detail.approval_route"
        :interrupt-id="detail.current_interrupt_id"
        :detail="detail"
        :loading="loading"
        @submit="submit"
      />
      <el-empty v-else description="当前无待处理审批" :image-size="60" />
      <el-alert v-if="detail.status === 'PAUSED' && detail.approval_status === 'PENDING_WRITE'"
        type="warning" :title="detail.approval_recovery_action === 'retry'
          ? '审批尚未调用外部 OA；权限恢复后可用原幂等键安全重试'
          : '审批写入结果未确认；请先用原幂等键向 OA 核对，不要再次批准'" :closable="false" show-icon />
      <el-button v-if="detail.status === 'PAUSED' && detail.approval_status === 'PENDING_WRITE'
          && (getCurrentUserId() === 'u_admin_001' || detail.approval_decisions?.at(-1)?.actor_id === getCurrentUserId())"
        :loading="loading" @click="reconcile">{{ detail.approval_recovery_action === 'retry' ? '安全重试' : '核对权威结果' }}</el-button>

      <h4>审批记录</h4>
      <el-timeline v-if="detail.approval_nodes?.length">
        <el-timeline-item v-for="node in detail.approval_nodes" :key="node.order" :type="node.status === 'APPROVED' ? 'success' : 'primary'">
          第 {{ node.order }} 级 · {{ node.approver_name }} · {{ node.status }}
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂未进入审批链" :image-size="56" />
      <el-descriptions v-for="(decision, index) in detail.approval_decisions || []" :key="index" :column="2" border size="small" class="decision">
        <el-descriptions-item label="决定">{{ decision.action }}</el-descriptions-item>
        <el-descriptions-item label="审批人">{{ decision.actor_id }}</el-descriptions-item>
        <el-descriptions-item label="意见" :span="2">{{ decision.comment || '-' }}</el-descriptions-item>
        <el-descriptions-item v-if="decision.action === 'reject'" label="驳回分类" :span="2">{{ decision.edited_data?.reason_category || 'other' }}</el-descriptions-item>
      </el-descriptions>

      <h4 v-if="detail.human_decision">最近人工决定</h4>
      <el-descriptions v-if="detail.human_decision" :column="2" border size="small">
        <el-descriptions-item label="动作">{{ detail.human_decision.action }}</el-descriptions-item>
        <el-descriptions-item label="操作者">{{ detail.human_decision.actor_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="意见" :span="2">{{ detail.human_decision.comment || '-' }}</el-descriptions-item>
      </el-descriptions>
    </template>
  </el-card>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h4 {
  margin: 16px 0 8px;
  color: #374151;
}
.decision { margin-top: 12px; }
</style>
