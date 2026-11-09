import { afterEach, beforeEach, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import * as icons from '@element-plus/icons-vue'
import App from '@/App.vue'
import { authState } from '@/stores/auth'
import { useAssistantStore } from '@/stores/assistant'

let wrapper: VueWrapper | undefined
beforeEach(() => {
  Object.assign(authState, { initialized: true, provider: 'builtin', aiEnabled: true, manualOA: true,
    user: { user_id: 'member', display_name: '成员', roles: [], depts: [], permissions:
      ['meeting', 'document'].map(resource => ({ resource, action: 'read', scope: 'self' })) } })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })
async function render() {
  let mounts = 0
  const page = { setup() { mounts++; return {} }, template: '<div>业务内容</div>' }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', redirect: '/meetings' }, { path: '/meetings', component: page }, { path: '/ticket/:id?', component: page },
  ] })
  await router.push('/meetings'); await router.isReady()
  wrapper = mount(App, { global: { plugins: [router, createPinia(), ElementPlus], components: icons } })
  await flushPromises()
  return { router, count: () => mounts }
}
it('groups permitted links, highlights aliases and provides a responsive navigation drawer', async () => {
  await render()
  const aside = wrapper!.get('.app-aside')
  expect(aside.text()).toContain('协同办公')
  expect(aside.text()).toContain('会议管理')
  expect(aside.text()).not.toContain('系统管理')
  expect(wrapper!.get('.app-breadcrumb').text()).toContain('会议管理')
  await wrapper!.get('button[aria-label="收起侧栏"]').trigger('click')
  expect(localStorage.getItem('oa-sidebar-collapsed')).toBe('true')
  await wrapper!.get('button[aria-label="打开导航"]').trigger('click')
  await flushPromises()
  expect(document.querySelector('.oa-nav-drawer')).not.toBeNull()
  expect(wrapper!.get('button[aria-label="打开导航"]').attributes('aria-expanded')).toBe('true')
})
it('does not remount on ordinary checks but resets the page when authorization changes', async () => {
  const { count } = await render()
  expect(count()).toBe(1)
  authState.user = { ...authState.user! }
  await flushPromises()
  expect(count()).toBe(1)
  authState.authorizationRevision++
  await flushPromises()
  expect(count()).toBe(2)
})
it('preserves the current mock ticket shortcut after grouping navigation', async () => {
  const { router } = await render()
  authState.provider = 'mock'
  const assistant = useAssistantStore()
  assistant.detail = { ticket: { ticket_id: 'TK-123' } } as any
  await flushPromises()
  const ticket = wrapper!.findAll('.app-aside .el-menu-item').find(item => item.text() === '工单查询')!
  await ticket.trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/ticket/TK-123')
  expect(ticket.classes()).toContain('is-active')
})
