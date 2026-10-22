<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 应用根组件。
 *
 * 使用 Element Plus 布局，左侧为导航菜单，右侧为路由视图。
 */
import { useRouter } from 'vue-router'
import { computed, watch, onBeforeUnmount } from 'vue'
import { useAssistantStore } from '@/stores/assistant'
import { ref } from 'vue'
import { getCurrentUserId, setCurrentUserId } from '@/api/client'
import { demoUsers, hasRole } from '@/utils/roles'
import { authState, can, logout } from '@/stores/auth'

const router = useRouter()
const assistant = useAssistantStore()
const currentUser = ref(getCurrentUserId())
const developerMode = import.meta.env.DEV
const builtin = computed(() => authState.provider === 'builtin')
const loginPage = computed(() => router.currentRoute.value.path === '/login')
const visible = (resource: string) => authState.aiEnabled && (!builtin.value || can(resource))
function resetIdentity() { assistant.$reset() }
window.addEventListener('oa-identity-changed', resetIdentity)
onBeforeUnmount(() => window.removeEventListener('oa-identity-changed', resetIdentity))
async function exit() { try { await logout() } finally { await router.replace('/login') } }
const isApprover = computed(() => hasRole(currentUser.value, 'approver'))
const isAdmin = computed(() => hasRole(currentUser.value, 'admin'))
const isSupport = computed(() => hasRole(currentUser.value, 'support'))
const leaveMenuPath = computed(() => '/leaves')
function switchUser(value: string) {
  assistant.clearDraft()
  setCurrentUserId(value)
  assistant.$reset()
  window.location.assign('/tasks')
}
const ticketMenuPath = computed(() =>
  assistant.detail?.ticket?.ticket_id ? `/ticket/${assistant.detail.ticket.ticket_id}` : '/ticket',
)
const activeMenu = computed(() => {
  const path = router.currentRoute.value.path
  if (path.startsWith('/oa/leaves')) return '/oa/leaves'
  if (path.startsWith('/oa/reimbursements')) return '/oa/reimbursements'
  if (path.startsWith('/oa/tickets')) return '/oa/tickets'
  if (path.startsWith('/oa/notifications')) return '/oa/notifications'
  if (path.startsWith('/oa/approvals')) return '/oa/approvals'
  if (path.startsWith('/oa/workflows')) return '/oa/workflows'
  if (path.startsWith('/oa/balances')) return '/oa/balances'
  if (path.startsWith('/oa/administration')) return '/oa/administration'
  if (path.startsWith('/leave/')) return leaveMenuPath.value
  if (path.startsWith('/leaves')) return '/leaves'
  if (path.startsWith('/assistant')) return '/assistant'
  if (path.startsWith('/meetings')) return '/meetings'
  if (path.startsWith('/documents')) return '/documents'
  if (path.startsWith('/emails')) return '/emails'
  if (path.startsWith('/work-tasks')) return '/work-tasks'
  if (path.startsWith('/reports')) return '/reports'
  if (path.startsWith('/contracts')) return '/contracts'
  if (path.startsWith('/ticket')) return ticketMenuPath.value
  if (path.startsWith('/support')) return '/support'
  return path
})

// 直接打开任务详情链接时，也将它登记为左侧菜单的当前待办入口。
watch(
  () => router.currentRoute.value.path,
  (path) => {
    const leaveMatch = path.match(/^\/leave\/([^/]+)$/)
    if (leaveMatch && leaveMatch[1] !== 'u_emp_001') {
      assistant.threadId = leaveMatch[1]
      assistant.persist()
    }
  },
  { immediate: true },
)
</script>

<template>
  <el-container class="app-container">
    <el-aside v-if="!loginPage && authState.initialized" width="232px" class="app-aside">
      <div class="logo">OA 工作平台</div>
      <div v-if="developerMode && !builtin" class="identity-switch"><span>开发演示账号</span><el-select v-model="currentUser" aria-label="当前演示账号" @change="switchUser"><el-option v-for="user in demoUsers" :key="user.id" :label="user.name" :value="user.id" /></el-select></div>
      <div v-if="builtin && authState.user" class="identity-switch"><router-link to="/account">{{ authState.user.display_name }}</router-link><el-button @click="exit">退出登录</el-button></div>
      <el-menu :default-active="activeMenu" router class="menu">
        <template v-if="builtin && authState.manualOA">
          <el-menu-item v-if="can('leave')" index="/oa/leaves"><el-icon><Document /></el-icon><span>我的申请</span></el-menu-item>
          <el-menu-item v-if="can('reimbursement')" index="/oa/reimbursements"><el-icon><Money /></el-icon><span>报销工作台</span></el-menu-item>
          <el-menu-item v-if="can('ticket') || can('ticket_handle')" index="/oa/tickets"><el-icon><Tickets /></el-icon><span>工单工作台</span></el-menu-item>
          <el-menu-item v-if="can('notification')" index="/oa/notifications"><el-icon><Bell /></el-icon><span>通知与站内信</span></el-menu-item>
          <el-menu-item v-if="can('approval')" index="/oa/approvals"><el-icon><DocumentChecked /></el-icon><span>审批工作台</span></el-menu-item>
          <el-menu-item v-if="can('leave_balance')" index="/oa/balances"><el-icon><DataAnalysis /></el-icon><span>请假额度</span></el-menu-item>
          <el-menu-item v-if="can('workflow')" index="/oa/workflows"><el-icon><SetUp /></el-icon><span>流程配置</span></el-menu-item>
          <el-menu-item v-if="can('workflow_admin')" index="/oa/administration"><el-icon><Warning /></el-icon><span>流程管理</span></el-menu-item>
        </template>
        <el-menu-item v-if="visible('thread')" index="/assistant">
          <el-icon><ChatDotRound /></el-icon>
          <span>智能助手</span>
        </el-menu-item>
        <el-menu-item v-if="visible('task')" index="/tasks"><el-icon><Grid /></el-icon><span>我的任务</span></el-menu-item>
        <el-menu-item v-if="visible('meeting')" index="/meetings"><el-icon><Document /></el-icon><span>会议文本</span></el-menu-item>
        <el-menu-item v-if="visible('document')" index="/documents"><el-icon><DocumentChecked /></el-icon><span>文档起草</span></el-menu-item>
        <el-menu-item v-if="visible('email')" index="/emails"><el-icon><Message /></el-icon><span>邮件工作台</span></el-menu-item>
        <el-menu-item v-if="visible('work_task')" index="/work-tasks"><el-icon><List /></el-icon><span>业务任务</span></el-menu-item>
        <el-menu-item v-if="visible('report')" index="/reports"><el-icon><DataAnalysis /></el-icon><span>只读报表</span></el-menu-item>
        <el-menu-item v-if="visible('contract')" index="/contracts"><el-icon><DocumentChecked /></el-icon><span>合同审查</span></el-menu-item>
        <el-menu-item v-if="builtin && can('organization')" index="/organization"><el-icon><OfficeBuilding /></el-icon><span>组织管理</span></el-menu-item>
        <el-menu-item v-if="authState.aiEnabled && !builtin" :index="leaveMenuPath">
          <el-icon><DocumentChecked /></el-icon>
          <span>我的请假</span>
        </el-menu-item>
        <el-menu-item v-if="authState.aiEnabled && !builtin && isApprover" index="/approvals"><el-icon><CircleCheck /></el-icon><span>审批待办</span></el-menu-item>
        <el-menu-item v-if="authState.aiEnabled && !builtin" :index="ticketMenuPath">
          <el-icon><Tickets /></el-icon>
          <span>工单查询</span>
        </el-menu-item>
        <el-menu-item v-if="authState.aiEnabled && !builtin && isSupport" index="/support">
          <el-icon><Service /></el-icon>
          <span>客服队列</span>
        </el-menu-item>
        <el-menu-item v-if="builtin ? can('policy') : isAdmin" index="/config">
          <el-icon><Setting /></el-icon>
          <span>智能配置</span>
        </el-menu-item>
        <el-menu-item v-if="builtin ? can('policy') : isAdmin" index="/config/policies">
          <el-icon><Setting /></el-icon>
          <span>策略版本</span>
        </el-menu-item>
        <el-menu-item v-if="builtin ? can('knowledge') : isAdmin" index="/knowledge">
          <el-icon><Collection /></el-icon>
          <span>知识库</span>
        </el-menu-item>
        <el-menu-item v-if="builtin ? can('knowledge') : isAdmin" index="/knowledge/sources">
          <el-icon><Collection /></el-icon>
          <span>来源治理</span>
        </el-menu-item>
        <el-menu-item v-if="builtin ? can('audit') : isAdmin" index="/audit">
          <el-icon><List /></el-icon>
          <span>审计中心</span>
        </el-menu-item>
        <el-menu-item v-if="builtin ? can('operations') : isAdmin" index="/operations"><el-icon><Monitor /></el-icon><span>运维观测</span></el-menu-item>
        <el-menu-item v-if="builtin ? can('operations') : isAdmin" index="/degradation"><el-icon><Warning /></el-icon><span>降级控制</span></el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="app-main" :class="{'login-main':loginPage}">
      <router-view :key="builtin ? authState.user?.user_id || 'anonymous' : currentUser" />
    </el-main>
  </el-container>
</template>

<style scoped>
.app-container {
  height: 100vh;
}
.app-aside {
  background: #e8f1f7;
  color: #17324d;
  border-right: 1px solid #d5e2ec;
}
.logo {
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 16px;
  letter-spacing: 0;
  color: #17324d;
  border-bottom: 1px solid #d5e2ec;
}
.menu {
  border-right: none;
  background: transparent;
  padding: 12px 10px;
}
.menu :deep(.el-menu-item) {
  height: 46px;
  line-height: 46px;
  margin: 4px 0;
  border-radius: 8px;
  color: #365269;
  font-weight: 500;
  transition: background-color 160ms ease, color 160ms ease, transform 160ms ease;
}
.menu :deep(.el-menu-item .el-icon) {
  color: #52718a;
  margin-right: 10px;
  font-size: 18px;
}
.menu :deep(.el-menu-item:hover) {
  background: #d5e9f1;
  color: #17324d;
}
.menu :deep(.el-menu-item:hover .el-icon) {
  color: #0f766e;
}
.menu :deep(.el-menu-item.is-active) {
  background: #0f766e;
  color: #ffffff;
  box-shadow: 0 4px 10px rgba(15, 118, 110, 0.2);
}
.menu :deep(.el-menu-item.is-active .el-icon) {
  color: #ffffff;
}
.menu :deep(.el-menu-item:focus-visible) {
  outline: 3px solid rgba(15, 118, 110, 0.28);
  outline-offset: 2px;
}
.app-main {
  background: #f4f7fb;
  padding: 20px;
  overflow: auto;
}
.identity-switch { display: grid; gap: 8px; padding: 16px; font-size: 12px; color: #52718a; }
.login-main { padding:0; }
@media (max-width: 720px) {
  .app-container { flex-direction: column; height: auto; min-height: 100vh; }
  .app-aside { width: 100% !important; }
  .logo { height: 48px; justify-content: flex-start; padding-left: 16px; }
  .identity-switch { grid-template-columns: auto minmax(140px, 240px); align-items: center; padding: 12px 16px; }
  .menu { display: flex; overflow-x: auto; padding: 4px 8px; }
  .menu :deep(.el-menu-item) { flex-shrink: 0; }
  .app-main { padding: 16px; }
}
</style>
