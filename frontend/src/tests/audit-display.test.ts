import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import AuditView from '@/views/AuditView.vue'
import { auditApi } from '@/api'

vi.mock('@/api', () => ({ auditApi: { query: vi.fn(), export: vi.fn(), download: vi.fn() } }))

beforeEach(() => {
  vi.mocked(auditApi.query).mockResolvedValue({
    items: [
      { id: 1, action: 'email_confirmed', result: 'success', target_id: 'MAIL-001' },
      { id: 2, action: 'work_task_archive', result: 'success', target_id: 'WT-001' },
      { id: 3, action: 'policy_changed', result: 'success', target_id: 'leave' },
    ], total: 3, page: 1, page_size: 20,
  } as any)
})

describe('audit display labels', () => {
  it('renders internal audit action codes and policy scenes in Chinese', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/audit', component: AuditView }] })
    await router.push('/audit')
    await router.isReady()
    const wrapper = mount(AuditView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('邮件确认')
    expect(wrapper.text()).toContain('业务任务归档')
    expect(wrapper.text()).toContain('请假审批策略已更新')
    expect(wrapper.text()).not.toContain('email_confirmed')
    expect(wrapper.text()).not.toContain('work_task_archive')
    expect(wrapper.text()).not.toContain('trace_id')
  })
})
