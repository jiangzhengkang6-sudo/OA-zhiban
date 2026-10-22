/**
 * OA 智能体系统 MVP - API 资源访问层。
 *
 * 聚合所有后端接口调用，返回解包后的 data 字段。
 */
import client from './client'
import type {
  ApiResponse,
  AuditEventOut,
  MessageCreateRequest,
  MessageResponse,
  PageResult,
  PolicyOut,
  PolicyUpdateRequest,
  PrecheckResponse,
  ResumeRequest,
  ResumeResponse,
  ThreadCreateRequest,
  ThreadDetail,
  ThreadResponse,
  TicketStatusResponse,
  TaskSummary,
  LeaveApplication,
  LeaveVersion,
  LeaveAttachment,
  SupportQueueItem,
  SupportQueueResponse,
  TicketFeedbackResponse,
  KnowledgePreview,
  KnowledgeVersion,
  PolicyVersion,
  RuntimeMetrics,
  RuntimeTraceDetail,
  DegradationState,
} from '@/types'
export { meetingApi } from './meeting'

/** 会话 */
export const threadApi = {
  create(payload: ThreadCreateRequest): Promise<ThreadResponse> {
    return client.post('/agent/threads', payload)
  },
  sendMessage(threadId: string, payload: MessageCreateRequest): Promise<MessageResponse> {
    return client.post(`/agent/threads/${threadId}/messages`, payload)
  },
  get(threadId: string): Promise<ThreadDetail> {
    return client.get(`/agent/threads/${threadId}`)
  },
}

export const taskApi = {
  list(params: Record<string, any> = {}): Promise<PageResult<TaskSummary>> {
    return client.get('/tasks', { params })
  },
  get(taskId: string): Promise<TaskSummary> { return client.get('/tasks/' + taskId) },
  handoff(taskId: string): Promise<TaskSummary> { return client.post('/tasks/' + taskId + '/handoff') },
  retry(taskId: string): Promise<TaskSummary> { return client.post('/tasks/' + taskId + '/retry') },
}

export const leaveApi = {
  list(params: Record<string, any> = {}): Promise<PageResult<LeaveApplication>> { return client.get('/leaves', { params }) },
  create(payload: Record<string, any>): Promise<LeaveApplication> { return client.post('/leaves', payload) },
  get(id: string): Promise<LeaveApplication> { return client.get('/leaves/' + id) },
  patch(id: string, payload: Record<string, any>): Promise<LeaveApplication> { return client.patch('/leaves/' + id, payload) },
  submit(id: string): Promise<LeaveApplication> { return client.post('/leaves/' + id + '/submit') },
  versions(id: string): Promise<LeaveVersion[]> { return client.get('/leaves/' + id + '/versions') },
  decide(id: string, payload: ResumeRequest): Promise<Record<string, any>> { return client.post('/leaves/' + id + '/decision', payload) },
  attachments(id: string): Promise<LeaveAttachment[]> { return client.get('/leaves/' + id + '/attachments') },
  uploadAttachment(id: string, file: File): Promise<LeaveAttachment> {
    const data = new FormData()
    data.append('file', file)
    return client.post('/leaves/' + id + '/attachments', data, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  scanAttachment(id: string, attachmentId: string): Promise<LeaveAttachment> {
    return client.post('/leaves/' + id + '/attachments/' + attachmentId + '/scan')
  },
  downloadAttachment(id: string, attachmentId: string): Promise<Blob> {
    return client.get('/leaves/' + id + '/attachments/' + attachmentId + '/content', { responseType: 'blob' })
  },
}

/** 中断恢复（HITL） */
export const interruptApi = {
  resume(interruptId: string, payload: ResumeRequest): Promise<ResumeResponse> {
    return client.post(`/agent/interrupts/${interruptId}/resume`, payload)
  },
}

/** 请假预检 */
export const approvalApi = {
  precheck(businessId: string): Promise<PrecheckResponse> {
    return client.post(`/approvals/${businessId}/precheck`, { business_id: businessId })
  },
  reconcile(threadId: string): Promise<{ thread_id: string; status: string }> {
    return client.post(`/approvals/threads/${threadId}/reconcile`)
  },
  retryWrite(threadId: string): Promise<{ thread_id: string; status: string }> {
    return client.post(`/approvals/threads/${threadId}/retry-write`)
  },
}

/** 工单 */
export const ticketApi = {
  get(ticketId: string): Promise<TicketStatusResponse> {
    return client.get(`/tickets/${ticketId}`)
  },
  getDraft(threadId: string) {
    return client.get(`/tickets/drafts/${threadId}`)
  },
  updateDraft(threadId: string, fields: Record<string, any>) {
    return client.patch(`/tickets/drafts/${threadId}`, { fields })
  },
  feedback(ticketId: string, payload: { resolved: boolean; comment: string; idempotency_key: string }): Promise<TicketFeedbackResponse> {
    return client.post(`/tickets/${ticketId}/feedback`, payload)
  },
}

export const supportApi = {
  list(params: Record<string, any> = {}): Promise<SupportQueueResponse> {
    return client.get('/support/queue', { params })
  },
  get(itemId: string): Promise<SupportQueueItem> {
    return client.get('/support/queue/' + itemId)
  },
  accept(itemId: string): Promise<SupportQueueItem> {
    return client.post('/support/queue/' + itemId + '/accept')
  },
  assign(itemId: string, assigneeId: string): Promise<SupportQueueItem> {
    return client.post('/support/queue/' + itemId + '/assign', { assignee_id: assigneeId })
  },
  complete(itemId: string, payload: { resolution: string; status: 'resolved' | 'closed' }): Promise<SupportQueueItem> {
    return client.post('/support/queue/' + itemId + '/complete', payload)
  },
}

/** 审计 */
export const auditApi = {
  query(params: Record<string, any>): Promise<PageResult<AuditEventOut>> {
    return client.get('/audit/events', { params })
  },
  export(filters: Record<string, any>): Promise<{ id: string; status: string; row_count: number; download_url: string }> { return client.post('/audit/exports', filters) },
  download(exportId: string): Promise<Blob> { return client.get('/audit/exports/' + exportId + '/download', { responseType: 'blob' }) },
}

export const operationsApi = {
  metrics(traceId?: string): Promise<RuntimeMetrics> { return client.get('/operations/metrics', { params: traceId ? { trace_id: traceId } : {} }) },
  trace(traceId: string): Promise<RuntimeTraceDetail> { return client.get('/operations/traces/' + encodeURIComponent(traceId)) },
  degradations(): Promise<DegradationState[]> { return client.get('/operations/degradations') },
  createDegradation(payload: Record<string, any>): Promise<DegradationState> { return client.post('/operations/degradations', payload) },
  restoreDegradation(id: string): Promise<DegradationState> { return client.post('/operations/degradations/' + id + '/restore') },
}

/** 策略 */
export const policyApi = {
  list(): Promise<PolicyOut[]> {
    return client.get('/admin/agent-policies')
  },
  upsert(payload: PolicyUpdateRequest): Promise<PolicyOut> {
    return client.put('/admin/agent-policies', payload)
  },
}

/** 知识库 */
export const knowledgeApi = {
  list(): Promise<any[]> {
    return client.get('/admin/knowledge')
  },
  import(payload: Record<string, any>): Promise<Record<string, any>> {
    return client.post('/admin/knowledge', payload)
  },
  updateStatus(id: string, status: string): Promise<any> {
    return client.put(`/admin/knowledge/${id}/status`, { status })
  },
  preview(file: File): Promise<KnowledgePreview> {
    const data = new FormData(); data.append('file', file)
    return client.post('/admin/knowledge/preview', data, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  createVersion(payload: Record<string, any>): Promise<KnowledgeVersion> {
    return client.post('/admin/knowledge/versions', payload)
  },
  uploadVersion(form: FormData): Promise<KnowledgeVersion> {
    return client.post('/admin/knowledge/versions/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  publishVersion(id: string): Promise<KnowledgeVersion> {
    return client.post(`/admin/knowledge/versions/${id}/publish`)
  },
}

export const policyVersionApi = {
  list(scene?: string): Promise<PolicyVersion[]> { return client.get('/admin/agent-policy-versions', { params: scene ? { scene } : {} }) },
  create(payload: Record<string, any>): Promise<PolicyVersion> { return client.post('/admin/agent-policy-versions', payload) },
  publish(id: string): Promise<PolicyVersion> { return client.post(`/admin/agent-policy-versions/${id}/publish`) },
  rollback(id: string): Promise<PolicyVersion> { return client.post(`/admin/agent-policy-versions/${id}/rollback`) },
}
