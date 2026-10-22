import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import TaskCenterView from '@/views/TaskCenterView.vue'
import AuditView from '@/views/AuditView.vue'
import { taskApi, auditApi } from '@/api'

vi.mock('@/api', () => ({
  taskApi: { list: vi.fn(), retry: vi.fn(), handoff: vi.fn() },
  approvalApi: { reconcile: vi.fn() },
  auditApi: { query: vi.fn(), export: vi.fn(), download: vi.fn() },
}))

const meetingTask = { task_id: 'thread-1', task_type: 'meeting', business_id: 'MTG-1', business_status: 'PAUSED',
  next_action: 'retry', responsibility: { role: 'employee', user_id: 'u_emp_001' }, available_actions: ['retry'], updated_at: '2026-10-14T00:00:00+08:00' }
async function render(component: any, path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/tasks', component: TaskCenterView },
    { path: '/meetings/:meetingId?', component: { template: '<div>会议工作台</div>' } },
    { path: '/audit', component: AuditView },
  ] })
  await router.push(path); await router.isReady()
  const wrapper = mount(component, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

describe('meeting navigation', () => {
  it('opens the owned meeting from its business id and routes retry to the workbench', async () => {
    vi.mocked(taskApi.list).mockResolvedValue({ items: [meetingTask], total: 1, page: 1, page_size: 20 } as any)
    const { wrapper, router } = await render(TaskCenterView, '/tasks?scene=meeting')
    expect(taskApi.list).toHaveBeenCalledWith(expect.objectContaining({ scene: 'meeting' }))
    expect(wrapper.text()).toContain('会议')
    await wrapper.findAll('button').find(button => button.text() === '安全重试')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/meetings/MTG-1')
    expect(taskApi.retry).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('loads the meeting audit filter from the link', async () => {
    vi.mocked(auditApi.query).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 } as any)
    const { wrapper } = await render(AuditView, '/audit?business_id=MTG-1')
    expect(auditApi.query).toHaveBeenCalledWith(expect.objectContaining({ business_id: 'MTG-1' }))
    expect(wrapper.get('input[placeholder="业务单据号"]').element).toHaveProperty('value', 'MTG-1')
    wrapper.unmount()
  })
})
