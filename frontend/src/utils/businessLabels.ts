import { demoUsers } from './roles'

export function personName(id: string | null | undefined): string {
  return demoUsers.find(user => user.id === id)?.name.split(' · ')[0] || id || '待分派'
}

const labels: Record<string, string> = {
  OPEN: '待受理', IN_PROGRESS: '处理中', RESOLVED: '已解决', CLOSED: '已关闭',
  open: '待处理', in_progress: '处理中', resolved: '已解决', closed: '已关闭',
  pending: '等待处理', within_sla: '时限内处理中', met: '已按时完成', unknown: '暂未确定',
  low: '低', normal: '普通', medium: '普通', high: '高', urgent: '紧急',
  user: '用户', assistant: '智能助手', system: '系统', tool: '工具',
  explicit: '原文明确提及', inferred: '根据原文推断', needs_confirmation: '待人工核实',
  ticket: '工单服务', faq: '知识问答', leave: '请假审批', meeting: '会议', approval: '审批',
  APPROVED: '已通过', REJECTED: '已拒绝', CANCELLED: '已取消', COMPLETED: '已完成',
  PAUSED: '已暂停', WAITING_HUMAN: '待人工处理', CREATED: '已创建',
  created: '创建任务', updated: '修改任务', start: '开始任务', progress: '更新进度',
  complete: '完成任务', cancel: '取消任务', archive: '归档任务',
}
export function businessLabel(value: string): string { return labels[value] || value }

export function sourceDescription(ref: string): string {
  const [type, id, version] = ref.split(':')
  if (!['meeting', 'ticket', 'approval'].includes(type) || !id) return '关联业务来源'
  const title = { meeting: '会议', ticket: '工单', approval: '审批' }[type]
  return `${title} ${id}${type !== 'ticket' && version ? ` · 第 ${version} 版` : ''}`
}

export function readableSource(content: string): unknown {
  try { return JSON.parse(content) } catch { /* Plain text sources remain unchanged. */ }
  const approval = content.match(/^(.+): (APPROVED|REJECTED|CANCELLED); version (\d+)$/)
  return approval ? `审批 ${approval[1]}：${businessLabel(approval[2])}，第 ${approval[3]} 版。` : content
}
