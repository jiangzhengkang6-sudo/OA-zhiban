import { authState, canAccessPath } from '@/stores/auth'

export interface NavigationItem { path: string; label: string; icon: string; aliases?: string[]; target?: string }
export interface NavigationGroup { id: string; label: string; icon: string; items: NavigationItem[] }
const definitions: NavigationGroup[] = [
  { id: 'workbench', label: '工作台', icon: 'Grid', items: [
    { path: '/tasks', label: '我的任务', icon: 'List' },
    { path: '/oa/notifications', label: '通知与站内信', icon: 'Bell' },
  ] },
  { id: 'business', label: '办公业务', icon: 'Briefcase', items: [
    { path: '/oa/leaves', label: '我的申请', icon: 'Document' },
    { path: '/oa/reimbursements', label: '报销工作台', icon: 'Money' },
    { path: '/oa/tickets', label: '工单工作台', icon: 'Tickets' },
    { path: '/oa/approvals', label: '审批工作台', icon: 'CircleCheck' },
    { path: '/oa/delegations', label: '审批委托', icon: 'Connection' },
    { path: '/oa/balances', label: '请假额度', icon: 'Calendar' },
    { path: '/leaves', label: '我的请假', icon: 'DocumentChecked', aliases: ['/leave'] },
    { path: '/approvals', label: '审批待办', icon: 'CircleCheck' },
    { path: '/ticket', label: '工单查询', icon: 'Tickets' },
    { path: '/support', label: '客服队列', icon: 'Service' },
  ] },
  { id: 'collaboration', label: '协同办公', icon: 'OfficeBuilding', items: [
    { path: '/oa/announcements', label: '部门公告', icon: 'ChatDotRound' },
    { path: '/meetings', label: '会议管理', icon: 'VideoCamera', aliases: ['/meeting-events', '/meeting-texts'] },
    { path: '/documents', label: '文档起草', icon: 'Document' },
    { path: '/emails', label: '邮件工作台', icon: 'Message' },
    { path: '/work-tasks', label: '业务任务', icon: 'List' },
  ] },
  { id: 'intelligence', label: '智能与知识', icon: 'MagicStick', items: [
    { path: '/assistant', label: '智能助手', icon: 'ChatDotRound' },
    { path: '/knowledge', label: '知识库', icon: 'Collection' },
    { path: '/contracts', label: '合同审查', icon: 'DocumentChecked' },
  ] },
  { id: 'reports', label: '数据报表', icon: 'DataAnalysis', items: [
    { path: '/reports', label: '只读报表', icon: 'DataAnalysis' },
  ] },
  { id: 'administration', label: '系统管理', icon: 'Setting', items: [
    { path: '/organization', label: '组织管理', icon: 'OfficeBuilding' },
    { path: '/oa/workflows', label: '流程配置', icon: 'Connection' },
    { path: '/oa/administration', label: '流程管理', icon: 'Setting' },
    { path: '/knowledge/sources', label: '来源治理', icon: 'Collection' },
    { path: '/config', label: '智能配置', icon: 'Setting' },
    { path: '/config/policies', label: '策略版本', icon: 'DocumentCopy' },
    { path: '/audit', label: '审计中心', icon: 'List' },
    { path: '/organization/alerts', label: '运行告警', icon: 'Warning' },
    { path: '/operations', label: '运维观测', icon: 'Monitor' },
    { path: '/degradation', label: '降级控制', icon: 'Warning' },
  ] },
]
const mockOnly = new Set(['/leaves', '/approvals', '/ticket', '/support'])
export function navigationGroups(): NavigationGroup[] {
  return definitions.map(group => ({ ...group, items: group.items.filter(item =>
    !(authState.provider === 'builtin' && mockOnly.has(item.path)) && canAccessPath(item.path)) }))
    .filter(group => group.items.length > 0)
}
export function navigationEntry(path: string) {
  const normalized = path.split(/[?#]/)[0] || '/'
  let found: { group: NavigationGroup; item: NavigationItem } | undefined
  let length = -1
  for (const group of definitions) for (const item of group.items) {
    for (const prefix of [item.path, ...(item.aliases || [])]) {
      if ((normalized === prefix || normalized.startsWith(prefix + '/')) && prefix.length > length) {
        found = { group, item }; length = prefix.length
      }
    }
  }
  return found
}
