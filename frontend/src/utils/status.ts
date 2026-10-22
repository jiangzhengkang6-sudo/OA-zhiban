/**
 * OA 智能体系统 MVP - 状态与枚举映射工具。
 *
 * 将后端枚举值映射为中文文案与 Element Plus 标签类型，集中维护便于统一展示。
 */

/** 编排状态 -> 中文 + 标签类型 */
export const STATUS_MAP: Record<string, { label: string; type: string }> = {
  DRAFT: { label: '草稿', type: 'info' },
  SUBMITTED: { label: '审批中', type: 'warning' },
  PRECHECK: { label: '预检中', type: 'primary' },
  NEEDS_FIX: { label: '待补充', type: 'warning' },
  ROUTING: { label: '路由中', type: 'primary' },
  WAITING_HUMAN: { label: '等待人工', type: 'warning' },
  ESCALATED: { label: '已升级', type: 'danger' },
  APPROVED: { label: '已批准', type: 'success' },
  REJECTED: { label: '已驳回', type: 'danger' },
  PAUSED: { label: '已暂停', type: 'info' },
  COMPLETED: { label: '已完成', type: 'success' },
}

/** 会议领域状态仅用于业务展示；任务筛选使用 AgentThread.status。 */
export const MEETING_STATUS_MAP: Record<string, { label: string; type: string }> = {
  CREATED: { label: '待生成', type: 'info' },
  PROCESSING: { label: '生成中', type: 'primary' },
  DRAFT_READY: { label: '待审阅', type: 'warning' },
  REVIEWING: { label: '已编辑 · 待审阅', type: 'warning' },
  CONFIRMED: { label: '已确认', type: 'success' },
}

/** P3 业务工作台状态仅用于展示，不能混入任务中心的编排状态筛选。 */
export const BUSINESS_STATUS_MAP: Record<string, { label: string; type: string }> = {
  PLAN_READY: { label: '待确认方案', type: 'warning' },
  OPEN: { label: '待开始', type: 'info' },
  IN_PROGRESS: { label: '进行中', type: 'primary' },
  CANCELLED: { label: '已取消', type: 'info' },
  ARCHIVED: { label: '已归档', type: 'info' },
  PUBLISHED: { label: '已发布', type: 'success' },
}

/** 意图 -> 中文 */
export const INTENT_MAP: Record<string, string> = {
  leave: '请假审批',
  faq: '知识问答',
  ticket: '工单办理',
  human: '转人工',
  unknown: '未知',
}

/** 预检项 -> 中文 */
export const PRECHECK_ITEM_MAP: Record<string, string> = {
  field: '必填字段',
  attachment: '附件完整性',
  balance: '假期余额',
  conflict: '时间冲突',
}

/** 场景 -> 中文 */
export const SCENE_MAP: Record<string, string> = {
  leave: '请假',
  faq: '问答',
  ticket: '工单',
  meeting: '会议',
  document: '文档',
  email: '邮件',
  work_task: '业务任务',
  report: '报表',
  contract: '合同审查',
}

/**
 * 获取状态展示信息。
 * @param status 状态码
 * @returns 中文标签与类型
 */
export function statusOf(status?: string | null): { label: string; type: string } {
  if (!status) return { label: '未知', type: 'info' }
  return STATUS_MAP[status] || MEETING_STATUS_MAP[status] || BUSINESS_STATUS_MAP[status] || { label: status, type: 'info' }
}

/**
 * 获取意图中文名。
 * @param intent 意图码
 * @returns 中文名
 */
export function intentLabel(intent?: string | null): string {
  if (!intent) return '未知'
  return INTENT_MAP[intent] || intent
}
