/**
 * OA 智能体系统 MVP - 路由配置。
 *
 * 六个页面路由：智能助手、请假详情、工单详情、智能配置、知识库、审计中心。
 */
import { createRouter, createWebHistory } from 'vue-router'
import { configureAuth, authState, canAccessPath, homePath, reloadIdentity, syncIdentity } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path:'/oa/delegations',component:()=>import('../views/OADelegationsView.vue') },
    { path:'/oa/announcements',component:()=>import('../views/AnnouncementView.vue') },
    { path:'/oa/leaves/:id?',component:()=>import('../views/OALeavesView.vue') },
    { path:'/oa/reimbursements/:id?',component:()=>import('../views/ReimbursementWorkbenchView.vue') },
    { path:'/oa/tickets/:ticketId?',component:()=>import('../views/TicketFormalWorkbenchView.vue') },
    { path:'/oa/notifications',component:()=>import('../views/NotificationWorkbenchView.vue') },
    { path:'/oa/approvals',component:()=>import('../views/OAApprovalsView.vue') },
    { path:'/oa/workflows',component:()=>import('../views/OAWorkflowView.vue') },
    { path:'/oa/balances',component:()=>import('../views/OABalancesView.vue') },
    { path:'/oa/administration',component:()=>import('../views/OAAdministrationView.vue') },
    { path: '/login', component: () => import('../views/LoginView.vue') },
    { path: '/organization', component: () => import('../views/OrganizationView.vue') },
    { path: '/organization/alerts', component: () => import('../views/OperationalAlertsView.vue') },
    { path: '/account', component: () => import('../views/AccountView.vue') },
    { path: '/', redirect: '/assistant' },
    {
      path: '/assistant/:threadId?',
      name: 'assistant',
      component: () => import('../views/AssistantView.vue'),
    },
    { path: '/tasks', component: () => import('../views/TaskCenterView.vue') },
    { path: '/meetings', name: 'meetings', component: () => import('../views/MeetingManagementView.vue') },
    { path: '/meeting-events/:id', component: () => import('../views/MeetingManagementView.vue') },
    { path: '/meeting-texts', component: () => import('../views/MeetingView.vue') },
    { path: '/meetings/:meetingId', component: () => import('../views/MeetingView.vue') },
    { path: '/documents/:id?', name: 'documents', component: () => import('../views/DocumentView.vue') },
    { path: '/emails', name: 'emails', component: () => import('../views/PublicMailboxView.vue') },
    { path: '/emails/manual-entry', component: () => import('../views/EmailView.vue') },
    { path: '/emails/:id', component: () => import('../views/EmailView.vue') },
    { path: '/work-tasks/:id?', name: 'work-tasks', component: () => import('../views/WorkTaskView.vue') },
    { path: '/reports/:id?', name: 'reports', component: () => import('../views/ReportView.vue') },
    { path: '/contracts/:id?', name: 'contracts', component: () => import('../views/ContractView.vue') },
    { path: '/leaves', component: () => import('../views/LeaveListView.vue') },
    { path: '/leaves/new', component: () => import('../views/LeaveFormView.vue') },
    { path: '/leaves/:applicationId', component: () => import('../views/LeaveFormView.vue') },
    { path: '/approvals', component: () => import('../views/ApprovalInboxView.vue') },
    {
      path: '/leave',
      name: 'leave-start',
      component: () => import('../views/AssistantView.vue'),
    },
    {
      path: '/leave/:threadId',
      name: 'leave-detail',
      component: () => import('../views/LeaveDetailView.vue'),
    },
    {
      path: '/ticket/:ticketId?',
      name: 'ticket-detail',
      component: () => import('../views/TicketDetailView.vue'),
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('../views/ConfigView.vue'),
    },
    {
      path: '/knowledge',
      name: 'knowledge',
      component: () => import('../views/KnowledgeView.vue'),
    },
    { path: '/knowledge/sources', name: 'knowledge-sources', component: () => import('../views/KnowledgeSourceView.vue') },
    { path: '/knowledge/sources/:sourceId/versions/:versionId', name: 'knowledge-reading', component: () => import('../views/KnowledgeReaderView.vue') },
    { path: '/config/policies', name: 'policy-versions', component: () => import('../views/PolicyVersionView.vue') },
    {
      path: '/audit',
      name: 'audit',
      component: () => import('../views/AuditView.vue'),
    },
    { path: '/operations', name: 'operations', component: () => import('../views/OperationsView.vue') },
    { path: '/degradation', name: 'degradation', component: () => import('../views/DegradationView.vue') },
    { path: '/support', name: 'support-queue', component: () => import('../views/SupportQueueView.vue') },
    { path: '/support/:itemId', name: 'support-item', component: () => import('../views/SupportWorkItemView.vue') },
    { path: '/support/ticket/:ticketId', name: 'support-ticket', component: () => import('../views/TicketWorkbenchView.vue') },
  ],
})

router.beforeEach(async (to) => {
  try { await configureAuth() } catch { return to.path === '/login' ? true : '/login' }
  if (authState.provider !== 'builtin') return to.path === '/login' || !canAccessPath(to.path) ? homePath() : true
  if (!authState.user) return to.path === '/login' ? true : {path:'/login', query:{redirect:to.fullPath}}
  if (to.path !== '/login') {
    try { await syncIdentity() } catch { /* Network failures do not revoke a valid session. */ }
    if (!authState.user) return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login') return homePath()
  return canAccessPath(to.path) ? true : homePath()
})
window.addEventListener('oa-session-expired', () => { void router.replace('/login') })
function enforceAccess() {
  const path = router.currentRoute.value.path
  if (path !== '/login' && !canAccessPath(path)) void router.replace(homePath())
}
window.addEventListener('oa-access-updated', enforceAccess)
window.addEventListener('oa-permissions-changed', async () => {
  try { await reloadIdentity() } catch { return }
  enforceAccess()
})
export default router
