<script setup lang="ts">
/**
 * OA 智能体系统 - 智能助手页面。
 *
 * 承载对话区、来源卡片、任务状态、转人工与工单确认等核心交互。
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { interruptApi, threadApi, ticketApi } from '@/api'
import type { ThreadDetail } from '@/types'
import { useAssistantStore } from '@/stores/assistant'
import { statusOf, intentLabel, SCENE_MAP } from '@/utils/status'
import StatusTag from '@/components/StatusTag.vue'
import SourceCard from '@/components/SourceCard.vue'
import PrecheckTable from '@/components/PrecheckTable.vue'
import { authState } from '@/stores/auth'
import { messageOf, oaLabel } from '@/utils/oa'
import AssistantV2Panel from '@/components/AssistantV2Panel.vue'

const assistant = useAssistantStore()
const route = useRoute()
const router = useRouter()
const activePanel = ref('v2')
const recovering = ref(false), recoveryError = ref('')
const scene = ref(route.path === '/leave' ? 'leave' : assistant.scene)
const businessId = ref(assistant.businessId)
const threadId = ref<string | null>(assistant.threadId)
const input = ref(assistant.input)
const sending = ref(false)
const creating = ref(false)
const detail = ref<ThreadDetail | null>(assistant.detail)
const ticketBusy = ref(false), ticketActionError = ref(''), editingTicket = ref(false)
const leaveBusy = ref(false), leaveActionError = ref('')
const actionBusy = computed(() => ticketBusy.value || leaveBusy.value)
const formalLeave = computed(() => authState.provider === 'builtin' && detail.value?.scene === 'leave')
const leaveCanConfirm = computed(() => formalLeave.value && !!detail.value?.current_interrupt_id &&
  detail.value.status === 'WAITING_HUMAN' && !detail.value.error &&
  ['DRAFT', 'REJECTED', 'CANCELLED'].includes(detail.value.approval_status || ''))
const editingInterrupt = ref<string | null>(null)
const ticketEdit = reactive({ summary: '', priority: 'medium' })
const priorityLabels: Record<string, string> = { low: '低', medium: '中', high: '高', urgent: '紧急' }
const ticketMessageBlocked = computed(() => authState.provider === 'builtin' && detail.value?.scene === 'ticket' &&
  !!(detail.value.current_interrupt_id || detail.value.business_id || detail.value.ticket?.ticket_id || detail.value.status === 'COMPLETED'))
const messageBlocked = computed(() => ticketMessageBlocked.value || (formalLeave.value &&
  !!(detail.value?.current_interrupt_id || detail.value?.status === 'COMPLETED')))
const ticketCanConfirm = computed(() => !!detail.value?.current_interrupt_id &&
  !detail.value.ticket?.ticket_id && (!detail.value.ticket_draft || detail.value.ticket_draft.status === 'PENDING') &&
  !detail.value.error)
const ticketReviewInvalid = computed(() => authState.provider === 'builtin' &&
  (!detail.value?.ticket_review || detail.value.ticket_review.expired || detail.value.ticket_review.changed))
const ticketSelection = computed(() => detail.value?.ticket_review?.target_ticket_id || 'new')

/** 对话展示列表（合并用户输入与系统结果） */
const chatLines = assistant.chatLines

watch(scene, (value) => {
  assistant.scene = value
  assistant.persist()
})
watch(businessId, (value) => {
  assistant.businessId = value
  assistant.persist()
})
watch(input, (value) => {
  assistant.input = value
  assistant.persist()
})

function saveState() {
  assistant.scene = scene.value
  assistant.businessId = businessId.value
  assistant.threadId = threadId.value
  assistant.input = input.value
  assistant.detail = detail.value
  assistant.persist()
}

/** 新建会话；请假场景必须关联已存在的 OA 请假单。 */
async function createThread(): Promise<boolean> {
  if (creating.value || recovering.value || actionBusy.value) return false
  const leaveBusinessId = businessId.value.trim()
  if (scene.value === 'leave' && !leaveBusinessId) {
    ElMessage.warning(authState.provider === 'builtin' ? '请先输入已保存的请假单号' : '请先输入已在 OA 中提交的请假单号')
    return false
  }

  creating.value = true
  try {
  const res = await threadApi.create({
    scene: scene.value,
    business_id: scene.value === 'leave' ? leaveBusinessId : undefined,
  })
  assistant.resetConversation()
  chatLines.splice(0, chatLines.length)
  detail.value = null
  ticketActionError.value = ''
  leaveActionError.value = ''
  editingTicket.value = false
  input.value = ''
  threadId.value = res.thread_id
  saveState()
  recoveryError.value = ''
  await router.replace('/assistant/' + res.thread_id)
  ElMessage.success(`会话已创建：${res.thread_id.slice(0, 8)}...`)
  return true
  } finally {
    creating.value = false
  }
}

/** 发送消息 */
async function send() {
  if (sending.value || creating.value || recovering.value || recoveryError.value || actionBusy.value || messageBlocked.value) return
  const content = input.value.trim()
  if (!content) return
  sending.value = true
  try {
  if (!threadId.value) {
    const created = await createThread()
    if (!created) return
  }
  chatLines.push({ role: 'user', content })
  saveState()
  input.value = ''
    await threadApi.sendMessage(threadId.value!, { content })
    await refresh()
  } finally {
    sending.value = false
  }
}

/** 刷新会话详情 */
async function refresh() {
  if (!threadId.value) return
  detail.value = await threadApi.get(threadId.value)
  scene.value = detail.value.scene
  businessId.value = detail.value.business_id || ''
  chatLines.splice(0, chatLines.length, ...detail.value.messages.map(message => ({ role: message.role, content: message.summary })))
  saveState()
}

/** 转人工 */
async function toHuman() {
  if (!threadId.value || actionBusy.value || messageBlocked.value) return
  chatLines.push({ role: 'user', content: '转人工' })
  saveState()
  await threadApi.sendMessage(threadId.value, { content: '转人工' })
  await refresh()
}

/** 工单确认/取消 */
async function confirmTicket(action: 'confirm' | 'cancel' | 'edit', editedData?: Record<string, string | number | null>) {
  const current = detail.value
  if (!current?.current_interrupt_id || !ticketCanConfirm.value || ticketBusy.value) return
  if (action === 'confirm' && ticketReviewInvalid.value) return
  ticketBusy.value = true
  ticketActionError.value = ''
  try {
    await interruptApi.resume(current.current_interrupt_id, {
      action,
      ...(editedData ? { edited_data: { ...editedData } } : {}),
      idempotency_key: `ticket:${current.thread_id}:${current.current_interrupt_id}:${action}`,
    })
    editingTicket.value = false
    await refresh()
  } catch (error) {
    ticketActionError.value = messageOf(error)
  } finally {
    ticketBusy.value = false
  }
}

async function selectTicket(value: string | number | boolean | undefined) {
  if (value === 'new') {
    await confirmTicket('edit', { merge_ticket_id: null, expected_revision: null })
    return
  }
  const candidate = detail.value?.ticket_candidates?.find(item => item.id === value)
  if (candidate) await confirmTicket('edit', { merge_ticket_id: candidate.id, expected_revision: candidate.revision })
}

async function refreshTicketReview() {
  const candidate = detail.value?.ticket_candidates?.find(item => item.id === ticketSelection.value)
  await confirmTicket('edit', candidate
    ? { merge_ticket_id: candidate.id, expected_revision: candidate.revision } : {})
}

function editTicketDraft() {
  if (!detail.value || !ticketCanConfirm.value || ticketBusy.value) return
  const current = detail.value.ticket_draft?.fields || detail.value.ticket_fields || {}
  Object.assign(ticketEdit, { summary: current.summary || '', priority: current.priority || 'medium' })
  editingInterrupt.value = detail.value.current_interrupt_id || null
  ticketActionError.value = ''
  editingTicket.value = true
}

async function saveTicketDraft() {
  if (!detail.value || ticketBusy.value || !ticketEdit.summary.trim()) return
  if (editingInterrupt.value !== detail.value.current_interrupt_id) {
    ticketActionError.value = '当前确认已变化，请刷新后重新编辑'
    return
  }
  const fields = { summary: ticketEdit.summary.trim(), priority: ticketEdit.priority }
  if (authState.provider === 'builtin') {
    await confirmTicket('edit', fields)
    return
  }
  ticketBusy.value = true
  ticketActionError.value = ''
  try {
    await ticketApi.updateDraft(detail.value.thread_id, fields)
    editingTicket.value = false
    await refresh()
  } catch (error) {
    ticketActionError.value = messageOf(error)
  } finally {
    ticketBusy.value = false
  }
}

function openTicket() {
  const id = detail.value?.ticket?.ticket_id
  if (id) router.push(authState.provider === 'builtin' ? `/oa/tickets/${id}` : `/ticket/${id}`)
}

async function reconcileTicket() {
  if (!detail.value?.current_interrupt_id || ticketBusy.value) return
  ticketBusy.value = true
  ticketActionError.value = ''
  try {
    await interruptApi.resume(detail.value.current_interrupt_id, { action: 'reconcile' })
    await refresh()
  } catch (error) {
    ticketActionError.value = messageOf(error)
  } finally {
    ticketBusy.value = false
  }
}

async function decideLeave(action: 'confirm' | 'cancel' | 'edit' | 'reconcile') {
  const current = detail.value
  if (!formalLeave.value || !current?.current_interrupt_id || actionBusy.value) return
  if (action !== 'reconcile' && !leaveCanConfirm.value) return
  leaveBusy.value = true
  leaveActionError.value = ''
  try {
    await interruptApi.resume(current.current_interrupt_id, action === 'reconcile' ? { action } : {
      action, idempotency_key: `leave:${current.thread_id}:${current.current_interrupt_id}:${action}`,
    })
    await refresh()
  } catch (error) {
    leaveActionError.value = messageOf(error)
  } finally {
    leaveBusy.value = false
  }
}

async function recover() {
  const id = String(route.params.threadId || route.query.threadId || assistant.threadId || '')
  if (!id) return
  if (creating.value && id === threadId.value) return
  recovering.value = true; recoveryError.value = ''; detail.value = null
  chatLines.splice(0, chatLines.length); threadId.value = id
  try { await refresh() } catch { threadId.value = null; assistant.clearDraft(); recoveryError.value = '历史会话加载失败，请确认当前账号权限后重试' }
  finally { recovering.value = false }
}
watch(() => route.params.threadId || route.query.threadId, recover, { immediate: true })
</script>

<template>
  <el-card shadow="never" class="assistant">
    <el-tabs v-model="activePanel" class="assistant-tabs">
      <el-tab-pane label="统一助手" name="v2">
        <AssistantV2Panel />
      </el-tab-pane>
      <el-tab-pane label="专项助手" name="special">
    <!-- 顶部：场景与会话控制 -->
    <div class="toolbar">
      <el-button type="primary" @click="router.push(authState.provider === 'builtin' ? '/oa/leaves/new' : '/leaves/new')">填写请假申请</el-button>
      <el-radio-group v-model="scene">
        <el-radio-button value="faq">知识问答</el-radio-button>
        <el-radio-button value="leave">请假审批</el-radio-button>
        <el-radio-button value="ticket">工单办理</el-radio-button>
      </el-radio-group>
      <el-input
        v-if="scene === 'leave'"
        v-model="businessId"
        placeholder="请输入 OA 请假单号"
        clearable
        style="width: 220px"
      />
      <el-button
        type="primary"
        plain
        :loading="creating"
        :disabled="sending || recovering || actionBusy || (scene === 'leave' && !businessId.trim())"
        @click="createThread"
      >
        新建会话
      </el-button>
      <el-button @click="toHuman" :disabled="!threadId || actionBusy || messageBlocked">转人工</el-button>
      <StatusTag v-if="detail" :status="detail.status" />
    </div>

    <el-alert
      v-if="scene === 'leave' && !threadId"
      :title="authState.provider === 'builtin' ? '请假申请' : '外部 OA 请假单'"
      type="warning"
      :closable="false"
      show-icon
      class="leave-guide"
    />
    <el-skeleton v-if="recovering" :rows="4" animated />
    <el-alert v-if="recoveryError" :title="recoveryError" type="error" :closable="false" /><el-button v-if="recoveryError" @click="recover">重新加载</el-button>
    <el-alert v-if="ticketActionError && !editingTicket" :title="ticketActionError" type="error" :closable="false" />
    <el-alert v-if="leaveActionError" :title="leaveActionError" type="error" :closable="false" />

    <!-- 会话状态条 -->
    <el-alert
      v-if="detail"
      :title="`场景：${SCENE_MAP[detail.scene] || detail.scene} | 意图：${intentLabel(detail.intent)} | 状态：${statusOf(detail.status).label}`"
      type="info"
      :closable="false"
      style="margin: 12px 0"
    />

    <!-- 异常状态：依赖失败/降级/暂停 -->
    <el-alert
      v-if="detail?.error"
      :title="`${detail.error.msg || '处理中断'}（${detail.error.code}）`"
      type="warning"
      :closable="false"
      show-icon
      style="margin: 12px 0"
    />
    <el-button v-if="authState.provider === 'builtin' && detail?.scene === 'ticket' && detail.error?.code === 'GRAPH_RECOVERY' && detail.current_interrupt_id"
      :disabled="ticketBusy" @click="reconcileTicket">恢复处理</el-button>
    <el-button v-if="formalLeave && detail?.error?.code === 'GRAPH_RECOVERY' && detail.current_interrupt_id"
      :disabled="actionBusy" @click="decideLeave('reconcile')">恢复处理</el-button>

    <!-- 对话区 -->
    <div class="chat-area">
      <div v-for="(line, i) in chatLines" :key="i" class="line" :class="line.role">
        <div class="bubble">{{ line.content }}</div>
      </div>

      <!-- 系统结果：FAQ 回答 + 来源 -->
      <div v-if="detail?.answer" class="line assistant">
        <div class="bubble">
          <div class="answer">{{ detail.answer.answer }}</div>
          <SourceCard :sources="detail.answer.sources" />
          <div class="conf">回答置信度：{{ (detail.answer.confidence ?? 0).toFixed(2) }}</div>
        </div>
      </div>

      <div v-if="detail?.scene === 'faq' && detail.handoff && !detail.answer" class="line assistant">
        <div class="bubble">知识库暂无足够可靠的依据，已转人工核实。不会自动创建工单。</div>
      </div>

      <!-- 系统结果：请假预检 -->
      <div v-if="detail?.precheck" class="line assistant">
        <div class="bubble">
          <PrecheckTable :precheck="detail.precheck" />
          <el-button
            v-if="detail.scene === 'leave' && detail.precheck?.passed && detail.business_id"
            type="primary"
            size="small"
            style="margin-top: 8px"
            @click="$router.push(`/leave/${detail.thread_id}`)"
          >
            查看审批详情
          </el-button>
        </div>
      </div>

      <section v-if="formalLeave && detail?.form_snapshot" class="leave-review">
        <el-descriptions title="请假申请" :column="1" border size="small">
          <el-descriptions-item label="申请编号">{{ detail.form_snapshot.business_no }}</el-descriptions-item>
          <el-descriptions-item label="假种">{{ oaLabel(detail.form_snapshot.leave_type) }}</el-descriptions-item>
          <el-descriptions-item label="日期">{{ detail.form_snapshot.start_date }} 至 {{ detail.form_snapshot.end_date }}</el-descriptions-item>
          <el-descriptions-item label="事由">{{ detail.form_snapshot.reason }}</el-descriptions-item>
          <el-descriptions-item label="申请状态">{{ oaLabel(detail.approval_status || '') }}</el-descriptions-item>
        </el-descriptions>
        <div class="leave-actions">
          <el-button :disabled="actionBusy" @click="router.push('/oa/leaves/' + detail.business_id)">打开请假单</el-button>
          <template v-if="leaveCanConfirm">
            <el-button :disabled="actionBusy" @click="decideLeave('edit')">刷新审核内容</el-button>
            <el-button :disabled="actionBusy" @click="decideLeave('cancel')">取消本次提交</el-button>
            <el-button type="primary" :disabled="actionBusy" @click="decideLeave('confirm')">确认提交请假</el-button>
          </template>
        </div>
      </section>

      <!-- 系统结果：工单草稿确认 -->
      <div v-if="detail?.scene === 'ticket' && (detail.ticket_draft || detail.ticket_fields) && !detail.ticket?.ticket_id" class="line assistant">
        <div class="bubble ticket-review">
          <el-descriptions title="工单草稿（请确认）" :column="1" border size="small">
            <el-descriptions-item label="类别">{{ (detail.ticket_draft?.fields || detail.ticket_fields)?.category }}</el-descriptions-item>
            <el-descriptions-item label="优先级">{{ priorityLabels[(detail.ticket_draft?.fields || detail.ticket_fields)?.priority] || '待确认' }}</el-descriptions-item>
            <el-descriptions-item label="摘要">{{ (detail.ticket_draft?.fields || detail.ticket_fields)?.summary }}</el-descriptions-item>
          </el-descriptions>
          <p v-if="detail.ticket_draft?.status === 'CANCELLED'">工单创建已取消</p>
          <template v-if="ticketCanConfirm && authState.provider === 'builtin'">
            <el-radio-group class="ticket-choices" :model-value="ticketSelection" :disabled="ticketBusy" aria-label="工单办理方式" @change="selectTicket">
              <el-radio value="new">新建工单</el-radio>
              <el-radio v-for="candidate in detail.ticket_candidates || []" :key="candidate.id" :value="candidate.id">
                合并到{{ candidate.business_no || '已有工单' }}：{{ candidate.summary }}（{{ candidate.reason }}）
              </el-radio>
            </el-radio-group>
            <p v-if="detail.ticket_review?.mode === 'merge'">合并目标：{{ detail.ticket_review.business_no }} · {{ detail.ticket_review.summary }}</p>
            <el-alert v-if="ticketReviewInvalid" :title="detail.ticket_review?.changed ? '目标工单已变化，请重新核对办理方式' : '审核内容已失效，请重新核对工单'" type="warning" :closable="false" />
          </template>
          <div v-if="ticketCanConfirm" class="ticket-actions">
            <el-button size="small" :disabled="ticketBusy" @click="editTicketDraft">编辑草稿</el-button>
            <el-button v-if="authState.provider === 'builtin'" size="small" :disabled="ticketBusy" @click="refreshTicketReview">重新核对工单</el-button>
            <el-button size="small" :disabled="ticketBusy" @click="confirmTicket('cancel')">取消</el-button>
            <el-button size="small" type="primary" :disabled="ticketBusy || ticketReviewInvalid" @click="confirmTicket('confirm')">{{ detail.ticket_review?.mode === 'merge' ? '确认合并工单' : '确认创建工单' }}</el-button>
          </div>
        </div>
      </div>

      <!-- 系统结果：工单已创建 -->
      <div v-if="detail?.scene === 'ticket' && detail.ticket?.ticket_id" class="line assistant">
        <div class="bubble">
          {{ detail.ticket.merged ? '已合并到工单' : '工单已创建' }}：<el-link type="primary" @click="openTicket">
            {{ detail.ticket.business_no || detail.ticket.ticket_id }}
          </el-link>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <el-input
        v-model="input"
        placeholder="请输入你的问题或描述..."
        :disabled="messageBlocked || actionBusy"
        @keyup.enter="send"
      />
      <el-button type="primary" :loading="sending" :disabled="recovering || !!recoveryError || messageBlocked || actionBusy" @click="send">发送</el-button>
    </div>
    <el-dialog v-model="editingTicket" title="编辑工单草稿" width="min(520px, calc(100vw - 32px))"
      :close-on-click-modal="!ticketBusy" :close-on-press-escape="!ticketBusy" :show-close="!ticketBusy">
      <el-alert v-if="ticketActionError" :title="ticketActionError" type="error" :closable="false" />
      <el-form label-position="top" :disabled="ticketBusy">
        <el-form-item label="问题摘要"><el-input v-model="ticketEdit.summary" type="textarea" :rows="4" maxlength="2000" /></el-form-item>
        <el-form-item label="优先级"><el-select v-model="ticketEdit.priority">
          <el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" />
          <el-option v-if="authState.provider !== 'builtin'" label="紧急" value="urgent" />
        </el-select></el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="ticketBusy" @click="editingTicket = false">取消编辑</el-button>
        <el-button type="primary" :disabled="ticketBusy || !ticketEdit.summary.trim()" @click="saveTicketDraft">保存修改</el-button>
      </template>
    </el-dialog>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.chat-area {
  min-height: 320px;
  max-height: 480px;
  overflow: auto;
  padding: 8px 0;
}
.leave-guide {
  margin: 12px 0;
}
.leave-review {
  margin: 12px 0;
  overflow-wrap: anywhere;
}
.leave-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.leave-actions .el-button + .el-button {
  margin-left: 0;
}
.ticket-review {
  min-width: 0;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  overflow-wrap: anywhere;
}
.ticket-review :deep(.el-descriptions__label) {
  width: 56px;
  white-space: nowrap;
}
.ticket-choices {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  width: 100%;
  margin-top: 12px;
}
.ticket-choices :deep(.el-radio) {
  height: auto;
  min-height: 44px;
  margin-right: 0;
  max-width: 100%;
  white-space: normal;
}
.ticket-choices :deep(.el-radio__label) {
  white-space: normal;
  line-height: 1.6;
}
.ticket-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.ticket-actions .el-button + .el-button {
  margin-left: 0;
}
.line {
  display: flex;
  margin: 8px 0;
}
.line.user {
  justify-content: flex-end;
}
.line.assistant {
  justify-content: flex-start;
}
.bubble {
  min-width: 0;
  max-width: 75%;
  box-sizing: border-box;
  overflow-wrap: anywhere;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f3f4f6;
  line-height: 1.6;
}
.line.user .bubble {
  background: #409eff;
  color: #fff;
}
.answer {
  white-space: pre-wrap;
}
.conf {
  color: #909399;
  font-size: 12px;
  margin-top: 6px;
}
.input-area {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
@media (max-width: 600px) {
  .bubble { max-width: 100%; }
  .line.user .bubble { max-width: 90%; }
}
</style>
