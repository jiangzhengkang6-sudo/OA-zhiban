/**
 * OA 智能体系统 MVP - 前端类型定义（与后端 Pydantic schema 对齐）。
 */

/** 统一 API 响应包装 */
export interface ApiResponse<T = unknown> {
  code: string
  message: string
  trace_id: string
  data: T | null
}

/** 分页结果 */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 创建会话 */
export interface ThreadCreateRequest {
  scene: string
  business_id?: string
}

export interface ThreadResponse {
  thread_id: string
  status: string
  business_id?: string | null
}

/** 发送消息 */
export interface MessageCreateRequest {
  content: string
  idempotency_key?: string
}

export interface MessageResponse {
  message_id: string
  status: string
  trace_id: string
  next_action?: string | null
}

/** 会话详情 */
export interface ThreadDetail {
  thread_id: string
  scene: string
  status: string
  intent?: string | null
  business_id?: string | null
  application_id?: string | null
  current_interrupt_id?: string | null
  next_action?: string | null
  messages: Array<{ role: string; summary: string; seq: number }>
  precheck?: PrecheckResult | null
  form_snapshot?: Record<string, any> | null
  approval_route?: ApprovalRoute | null
  approval_status?: string | null
  approval_recovery_action?: 'retry' | 'reconcile' | null
  active_approval_node?: { node_id: string; order: number; approver_id: string; approver_name: string } | null
  approval_nodes?: Array<{ order: number; approver_id: string; approver_name: string; status: string }>
  approval_decisions?: Array<{ actor_id: string; action: string; comment: string; edited_data?: Record<string, any> | null; created_at: string }>
  human_decision?: Record<string, any> | null
  answer?: Answer | null
  ticket?: Record<string, any> | null
  ticket_fields?: Record<string, any> | null
  ticket_draft?: { thread_id: string; fields: Record<string, any>; extracted_fields?: Record<string, any>; status: string } | null
  ticket_candidates?: Array<{ id: string; business_no?: string; revision: number; summary: string; state: string; score: number; reason: string }>
  ticket_review?: { mode: 'new' | 'merge'; target_ticket_id?: string | null; expected_revision?: number | null;
    business_no?: string; summary?: string; expires_at?: string; expired: boolean; changed: boolean } | null
  handoff?: { queue_item_id: string; reason_code: string } | null
  error?: { code: string; msg: string } | null
  created_at?: string | null
  updated_at?: string | null
}

export interface TaskSummary {
  task_id: string
  task_type: string
  business_id?: string | null
  business_status: string
  next_action?: string | null
  responsibility: { role: string; user_id?: string | null; display_name?: string | null; waiting_since?: string | null }
  available_actions: string[]
  pause_reason?: Record<string, any> | null
  created_at?: string | null
  updated_at?: string | null
}

export interface LeaveApplication {
  application_id: string
  thread_id?: string | null
  business_id: string
  user_id: string
  status: string
  version: number
  fields: Record<string, any>
  precheck?: PrecheckResult | null
  created_at?: string | null
  updated_at?: string | null
}

export interface LeaveVersion {
  version: number
  status: string
  fields: Record<string, any>
  precheck?: PrecheckResult | null
  created_at?: string | null
}

/** 请假申请附件元数据（文件内容不直接进入业务 JSON）。 */
export interface LeaveAttachment {
  attachment_id: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  scan_status: 'PENDING' | 'CLEAN' | 'INFECTED' | 'ERROR' | string
}

/** 单条预检项 */
export interface PrecheckItem {
  item: string
  result: string
  reason?: string
  suggestion?: string
}

/** 预检结果 */
export interface PrecheckResult {
  results: PrecheckItem[]
  passed: boolean
  rule_version: string
}

/** 独立请假预检接口响应 */
export interface PrecheckResponse {
  business_id: string
  precheck_result: PrecheckItem[]
  passed: boolean
  status: string
  rule_version: string
}

/** 审批链节点 */
export interface ApprovalNode {
  order: number
  approver_id: string
  approver_name: string
  is_proxy: boolean
}

/** 审批链建议 */
export interface ApprovalRoute {
  business_id: string
  nodes: ApprovalNode[]
  rule_version: string
  risk_hint: string
  conflict: boolean
}

/** FAQ 回答 */
export interface Answer {
  answer: string
  sources: Array<{
    document_id: string
    title: string
    source_location: string
    similarity: number
  }>
  confidence: number
}

/** 中断恢复 */
export interface ResumeRequest {
  action: string
  comment?: string
  edited_data?: Record<string, any>
  idempotency_key?: string
}

export interface ResumeResponse {
  status: string
  next_action?: string | null
  trace_id: string
}

/** 工单查询 */
export interface TicketStatusResponse {
  ticket: Record<string, any>
  timeline: Array<Record<string, any>>
}

export interface SupportQueueItem {
  queue_item_id: string
  tenant_id: string
  thread_id: string
  user_id: string
  scene: string
  reason_code: string
  status: string
  assignee_id?: string | null
  context_summary?: string | null
  snapshot: Record<string, any>
  ticket_id?: string | null
  ticket_status?: string | null
  sla_status: string
}

export interface SupportQueueResponse extends PageResult<SupportQueueItem> {}

export interface TicketFeedbackResponse {
  feedback_id: string
  ticket_id: string
  ticket_status?: string | null
  review_queue_item_id?: string | null
  resolved: boolean
}

/** 审计事件 */
export interface AuditEventOut {
  id: number | string
  trace_id?: string | null
  thread_id?: string | null
  business_id?: string | null
  actor_id?: string | null
  action: string
  target_type?: string | null
  target_id?: string | null
  tool_name?: string | null
  result?: string | null
  error_code?: string | null
  policy_version?: string | null
  duration_ms?: number | null
  created_at?: string | null
  input_summary?: Record<string, any> | null
  output_summary?: Record<string, any> | null
}

/** 策略 */
export interface PolicyOut {
  scene: string
  scope_type: string
  scope_value?: string | null
  enabled: boolean
  thresholds: Record<string, any>
  rule_version: string
  updated_by?: string | null
}

export interface PolicyUpdateRequest {
  scene: string
  scope_type: string
  scope_value?: string | null
  enabled: boolean
  thresholds: Record<string, any>
  rule_version: string
}

export interface KnowledgeVersion {
  id: string
  source_id: string
  version: number
  status: string
  parse_status: string
  content_hash?: string | null
  permission_tags: string[]
  effective_at?: string | null
  expire_at?: string | null
}

export interface KnowledgePreview {
  filename: string
  format: string
  content_hash: string
  file_reference?: string
  blocks: Array<{ text: string; page?: number | null; section?: string | null; paragraph?: number | null }>
}

export interface PolicyVersion {
  id: string
  scene: string
  scope_type: string
  scope_value?: string | null
  version: number
  status: string
  enabled: boolean
  thresholds: Record<string, any>
  rule_version: string
  created_by?: string | null
  published_at?: string | null
}

export interface RuntimeMetrics { span_count: number; error_count: number; avg_duration_ms: number | null; total_duration_ms: number; usage_count: number; usage_missing_count: number; total_tokens: number | null }
export interface RuntimeSpan { id: string; run_id: string; node_name: string; tool_name?: string | null; duration_ms?: number | null; status: string; error_code?: string | null; started_at?: string | null; finished_at?: string | null }
export interface ModelUsage { id: string; run_id: string; provider: string; model_name: string; input_tokens?: number | null; output_tokens?: number | null; total_tokens?: number | null; usage_missing: boolean }
export interface RuntimeTraceDetail { trace_id: string; spans: RuntimeSpan[]; model_usage: ModelUsage[] }
export interface DegradationState { id: string; scene: string; scope_type: string; scope_value?: string | null; enabled: boolean; new_task_action: string; inflight_action: string; reason: string; created_by: string; restored_by?: string | null; restored_at?: string | null; created_at?: string | null }

export type MeetingStatus = 'CREATED' | 'PROCESSING' | 'DRAFT_READY' | 'REVIEWING' | 'PAUSED' | 'CONFIRMED' | 'REJECTED'
export interface MeetingSegment { segment_id: string; ordinal: number; start_offset: number; end_offset: number; text: string; locator: string; text_hash: string; summary: string }
export interface MeetingDecisionCandidate { text: string; source_refs: string[]; confidence: 'explicit' | 'inferred' | 'needs_confirmation' }
export interface MeetingActionItem { title: string; assignee_candidate?: string | null; due_at_candidate?: string | null; priority: 'low' | 'medium' | 'high'; source_refs: string[]; needs_confirmation: boolean }
export interface MeetingDraft { summary: string; topics: string[]; decisions: MeetingDecisionCandidate[]; action_items: MeetingActionItem[]; source_refs: string[] }
export interface MeetingResponse { meeting_id: string; thread_id?: string | null; status: MeetingStatus; title: string; version?: number | null; segments: MeetingSegment[]; draft?: MeetingDraft | null; available_actions: string[]; trace_id: string; external_writes: boolean; created_at?: string | null; updated_at?: string | null }
export interface MeetingSummary { meeting_id: string; thread_id?: string | null; title: string; status: MeetingStatus; version?: number | null; available_actions: string[]; external_writes: boolean; created_at?: string | null; updated_at?: string | null }
export interface MeetingPage extends PageResult<MeetingSummary> {}
export interface MeetingCreateRequest { title: string; content: string; source_type?: 'paste' | 'import' | 'api'; idempotency_key?: string }
export interface MeetingDraftUpdateRequest { draft: MeetingDraft; expected_version: number; idempotency_key: string }
export interface MeetingDecisionRequest { action: 'confirm' | 'reject' | 'regenerate'; reason?: string | null; expected_version: number; idempotency_key: string }
