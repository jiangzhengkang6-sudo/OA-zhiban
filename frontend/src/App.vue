<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Expand, Fold, Menu, Close, Bell, ArrowDown, User, SwitchButton, OfficeBuilding } from '@element-plus/icons-vue'
import { useAssistantStore } from '@/stores/assistant'
import { getCurrentUserId, setCurrentUserId } from '@/api/client'
import { demoUsers } from '@/utils/roles'
import { authState, canAccessPath, logout, startIdentitySync } from '@/stores/auth'
import { navigationGroups, navigationEntry } from '@/navigation'
import AppNavigation from '@/components/AppNavigation.vue'

const router = useRouter()
const assistant = useAssistantStore()
const currentUser = ref(getCurrentUserId())
const developerMode = import.meta.env.DEV
const builtin = computed(() => authState.provider === 'builtin')
const loginPage = computed(() => router.currentRoute.value.path === '/login')
const ready = computed(() => !loginPage.value && authState.initialized)
const groups = computed(() => navigationGroups().map(group => ({ ...group, items: group.items.map(item =>
  item.path === '/ticket' && !builtin.value && assistant.detail?.ticket?.ticket_id
    ? { ...item, target: `/ticket/${encodeURIComponent(assistant.detail.ticket.ticket_id)}` } : item) })))
const entry = computed(() => navigationEntry(router.currentRoute.value.path))
const activeMenu = computed(() => entry.value?.item.path || '')
const pageTitle = computed(() => router.currentRoute.value.path === '/account' ? '个人账户' : entry.value?.item.label || 'OA 工作平台')
const userName = computed(() => builtin.value ? authState.user?.display_name || '用户' : demoUsers.find(user => user.id === currentUser.value)?.name || '演示账号')
function readCollapsed() { try { return localStorage.getItem('oa-sidebar-collapsed') === 'true' } catch { return false } }
const collapsed = ref(readCollapsed())
const mobileOpen = ref(false)
watch(collapsed, value => { try { localStorage.setItem('oa-sidebar-collapsed', String(value)) } catch { /* Optional preference. */ } })
function resetIdentity() { assistant.$reset() }
window.addEventListener('oa-identity-changed', resetIdentity)
const stopSync = startIdentitySync()
onBeforeUnmount(() => { window.removeEventListener('oa-identity-changed', resetIdentity); stopSync() })
async function exit() { try { await logout() } finally { await router.replace('/login') } }
function accountCommand(command: string) {
  if (command === 'logout') void exit()
  else void router.push('/account')
}
function switchUser(value: string) {
  assistant.clearDraft()
  setCurrentUserId(value)
  assistant.$reset()
  window.location.assign('/tasks')
}
watch(() => router.currentRoute.value.path, path => {
  mobileOpen.value = false
  const match = path.match(/^\/leave\/([^/]+)$/)
  if (match && match[1] !== 'u_emp_001') { assistant.threadId = match[1]; assistant.persist() }
}, { immediate: true })
const viewKey = computed(() => builtin.value ? `${authState.user?.user_id || 'anonymous'}:${authState.authorizationRevision}` : currentUser.value)
</script>

<template>
  <div class="oa-app" :class="{ 'is-collapsed': collapsed }">
    <a v-if="ready" class="skip-link" href="#main-content">跳到主要内容</a>
    <aside v-if="ready" class="app-aside">
      <router-link class="brand" to="/" aria-label="OA 工作平台首页">
        <span class="brand-mark"><el-icon><OfficeBuilding /></el-icon></span>
        <span v-if="!collapsed" class="brand-title">OA 工作平台</span>
      </router-link>
      <AppNavigation :groups="groups" :active="activeMenu" :collapsed="collapsed" />
      <div class="sidebar-footer">
        <el-tooltip :content="collapsed ? '展开侧栏' : '收起侧栏'" placement="right">
          <el-button text class="sidebar-toggle" :aria-label="collapsed ? '展开侧栏' : '收起侧栏'" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
            <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon><span v-if="!collapsed">收起侧栏</span>
          </el-button>
        </el-tooltip>
      </div>
    </aside>
    <div class="app-body">
      <header v-if="ready" class="app-topbar">
        <el-button text :icon="Menu" class="mobile-menu-toggle" aria-label="打开导航" :aria-expanded="mobileOpen" @click="mobileOpen = true" />
        <el-breadcrumb separator="/" class="app-breadcrumb" aria-label="当前位置">
          <el-breadcrumb-item v-if="entry">{{ entry.group.label }}</el-breadcrumb-item>
          <el-breadcrumb-item>{{ pageTitle }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="topbar-actions">
          <div v-if="developerMode && !builtin" class="demo-account"><span>演示账号</span><el-select v-model="currentUser" aria-label="当前演示账号" @change="switchUser"><el-option v-for="user in demoUsers" :key="user.id" :label="user.name" :value="user.id" /></el-select></div>
          <el-tooltip v-if="builtin && canAccessPath('/oa/notifications')" content="通知与站内信" placement="bottom">
            <el-button text :icon="Bell" aria-label="通知与站内信" @click="router.push('/oa/notifications')" />
          </el-tooltip>
          <el-dropdown trigger="click" @command="accountCommand">
            <button class="account-trigger" type="button" aria-label="账户菜单">
              <span class="account-avatar">{{ userName.slice(0, 1) }}</span><span class="account-name">{{ userName }}</span><el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item command="account" :icon="User">个人账户</el-dropdown-item><el-dropdown-item v-if="builtin" command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </header>
      <main id="main-content" class="app-main" :class="{ 'login-main': loginPage }" tabindex="-1">
        <router-view :key="viewKey" />
      </main>
    </div>
    <el-drawer v-if="ready" v-model="mobileOpen" direction="ltr" size="264px" :with-header="false" append-to-body class="oa-nav-drawer" aria-label="导航菜单">
      <div class="mobile-brand"><span class="brand-title">OA 工作平台</span><el-button text :icon="Close" aria-label="关闭导航" @click="mobileOpen = false" /></div>
      <AppNavigation :groups="groups" :active="activeMenu" @navigate="mobileOpen = false" />
    </el-drawer>
  </div>
</template>
